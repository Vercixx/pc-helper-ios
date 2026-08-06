#!/usr/bin/env python3
"""Reference client for the wol-unlock v1 protocol.

Deliberately **self-contained**: it implements the canonical strings straight
from ``docs/PROTOCOL.md`` instead of importing ``wol_unlock.crypto.canonical``.
Sharing that module would mean a bug in it could never be caught here, because
both sides would make the same mistake. Written against nothing but the standard
library plus ``cryptography``, it doubles as the reference the TypeScript client
is checked against.

Usage
-----
    ./refclient.py pair   --host my-pc.local --code K7M2-QX4B
    ./refclient.py status
    ./refclient.py unlock
    ./refclient.py wake
    ./refclient.py replay     # reuse a nonce; expects 401 replayed_nonce
    ./refclient.py tamper     # body != signed hash; expects 401
    ./refclient.py stale      # old timestamp; expects 401
    ./refclient.py selftest   # every negative case in one run

State (device private key, server public key, address) lives in
``~/.config/wol-unlock/refclient.json`` unless ``--state`` says otherwise.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

DEFAULT_PORT = 8765
DEFAULT_STATE = Path.home() / ".config" / "wol-unlock" / "refclient.json"


# --------------------------------------------------------------------------- #
# Encoding (PROTOCOL.md 1)
# --------------------------------------------------------------------------- #

def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * ((-len(text)) % 4))


def sha256_b64u(data: bytes) -> str:
    return b64u(hashlib.sha256(data).digest())


def fingerprint(pubkey: bytes) -> str:
    return b64u(hashlib.sha256(pubkey).digest())


def device_id_for(pubkey: bytes) -> str:
    return b64u(hashlib.sha256(pubkey).digest()[:16])


# --------------------------------------------------------------------------- #
# Canonical strings (PROTOCOL.md 2)
# --------------------------------------------------------------------------- #

def canonical_request(method, path, timestamp, nonce, body_sha256, device_id, server_fp) -> bytes:
    return (
        "wol-unlock/v1/request\n"
        f"{method}\n{path}\n{timestamp}\n{nonce}\n{body_sha256}\n{device_id}\n{server_fp}\n"
    ).encode("ascii")


def canonical_response(status, nonce_echo, body_sha256, server_fp) -> bytes:
    return (
        f"wol-unlock/v1/response\n{status}\n{nonce_echo}\n{body_sha256}\n{server_fp}\n"
    ).encode("ascii")


def canonical_pair(code, device_pubkey_b64, server_fp) -> bytes:
    return (
        f"wol-unlock/v1/pair\n{code}\n{device_pubkey_b64}\n{server_fp}\n"
    ).encode("ascii")


def normalize_code(value: str) -> str:
    cleaned = "".join(ch for ch in value.upper() if ch.isalnum())
    return cleaned.translate(str.maketrans({"I": "1", "L": "1", "O": "0", "U": "V"}))


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #

class State:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = {}
        if path.exists():
            self.data = json.loads(path.read_text())

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(self.data, handle, indent=2)
        os.replace(tmp, self.path)

    @property
    def private_key(self) -> Ed25519PrivateKey:
        seed = self.data.get("device_seed")
        if not seed:
            raise SystemExit("not paired yet -- run 'refclient.py pair' first")
        return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed))

    def require(self, key: str) -> Any:
        if key not in self.data:
            raise SystemExit(f"not paired yet (missing {key}) -- run 'refclient.py pair' first")
        return self.data[key]


# --------------------------------------------------------------------------- #
# Transport
# --------------------------------------------------------------------------- #

class ApiFailure(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self.message = message
        super().__init__(f"HTTP {status} {code}: {message}")


def _request(url: str, method: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes, Any]:
    req = urllib.request.Request(url, data=body if method == "POST" else None, method=method)
    for key, value in headers.items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=75) as resp:
            return resp.status, resp.read(), resp.headers
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers
    except urllib.error.URLError as exc:
        raise SystemExit(f"cannot reach {url}: {exc.reason}") from exc


class Client:
    def __init__(self, state: State, host: str | None = None, port: int | None = None) -> None:
        self.state = state
        self.host = host or state.data.get("host") or "localhost"
        self.port = port or state.data.get("port") or DEFAULT_PORT
        #: Turned off only by the cross-server test below, which deliberately
        #: pins the wrong key. Real clients must always leave this on.
        self.verify_responses = True

    @property
    def base(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _verify_response(self, status: int, body: bytes, headers: Any, nonce_echo: str) -> None:
        """Check the server signature before trusting anything in the body.

        Skipped only before pairing, when no server key is known yet.
        """
        server_pub = self.state.data.get("server_pubkey")
        if not server_pub or not self.verify_responses:
            return
        signature = headers.get("X-WU-Server-Signature")
        if not signature:
            raise ApiFailure(status, "unsigned_response", "response carried no server signature")
        message = canonical_response(
            status, nonce_echo, sha256_b64u(body), fingerprint(unb64u(server_pub))
        )
        try:
            Ed25519PublicKey.from_public_bytes(unb64u(server_pub)).verify(
                unb64u(signature), message
            )
        except (InvalidSignature, ValueError) as exc:
            raise ApiFailure(
                status, "bad_server_signature", "response signature did not verify"
            ) from exc

    def call(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        nonce: str | None = None,
        timestamp: int | None = None,
        send_body: bytes | None = None,
    ) -> dict[str, Any]:
        """Signed request. ``nonce``/``timestamp``/``send_body`` exist so the
        negative tests can deviate from the happy path deliberately."""
        device_id = self.state.require("device_id")
        server_fp = fingerprint(unb64u(self.state.require("server_pubkey")))

        body = b"" if payload is None else json.dumps(payload, separators=(",", ":")).encode()
        nonce = nonce or b64u(secrets.token_bytes(16))
        timestamp = timestamp or int(time.time())

        signature = self.state.private_key.sign(
            canonical_request(
                method, path, timestamp, nonce, sha256_b64u(body), device_id, server_fp
            )
        )
        headers = {
            "X-WU-Version": "1",
            "X-WU-Device": device_id,
            "X-WU-Timestamp": str(timestamp),
            "X-WU-Nonce": nonce,
            "X-WU-Signature": b64u(signature),
            "Content-Type": "application/json",
        }
        # send_body lets us transmit bytes other than the ones we signed.
        on_wire = body if send_body is None else send_body
        status, raw, resp_headers = _request(self.base + path, method, on_wire, headers)
        self._verify_response(status, raw, resp_headers, nonce)

        parsed = json.loads(raw)
        if not parsed.get("ok"):
            err = parsed.get("error", {})
            raise ApiFailure(status, err.get("code", "error"), err.get("message", ""))
        return parsed.get("data", {})

    def server_info(self) -> dict[str, Any]:
        status, raw, headers = _request(self.base + "/v1/server-info", "GET", b"", {})
        self._verify_response(status, raw, headers, "")
        parsed = json.loads(raw)
        if not parsed.get("ok"):
            err = parsed.get("error", {})
            raise ApiFailure(status, err.get("code", "error"), err.get("message", ""))
        return parsed.get("data", {})

    def pair(self, code: str, name: str) -> dict[str, Any]:
        info = self.server_info()
        server_fp = info["fp"]

        seed = secrets.token_bytes(32)
        private = Ed25519PrivateKey.from_private_bytes(seed)
        pubkey = private.public_key().public_bytes_raw()

        normalized = normalize_code(code)
        proof = private.sign(canonical_pair(normalized, b64u(pubkey), server_fp))

        payload = {
            "v": 1,
            "code": normalized,
            "device_pubkey": b64u(pubkey),
            "device_name": name,
            "platform": "refclient",
            "proof": b64u(proof),
        }
        status, raw, _ = _request(
            self.base + "/v1/pair",
            "POST",
            json.dumps(payload).encode(),
            {"Content-Type": "application/json"},
        )
        parsed = json.loads(raw)
        if not parsed.get("ok"):
            err = parsed.get("error", {})
            raise ApiFailure(status, err.get("code", "error"), err.get("message", ""))

        data = parsed["data"]
        if fingerprint(unb64u(data["server_pubkey"])) != data["server_fp"] != server_fp:
            raise SystemExit("server fingerprint mismatch -- refusing to trust this server")
        if device_id_for(pubkey) != data["device_id"]:
            raise SystemExit("server issued a device_id we did not derive -- aborting")

        self.state.data.update(
            {
                "device_seed": seed.hex(),
                "device_id": data["device_id"],
                "server_pubkey": data["server_pubkey"],
                "server_fp": data["server_fp"],
                "server_name": data.get("name"),
                "host": self.host,
                "port": self.port,
                "wake": data.get("wake"),
                "paired_at": int(time.time()),
            }
        )
        self.state.save()
        return data


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def _print(label: str, value: Any) -> None:
    print(f"  {label:<22}{value}")


def cmd_pair(client: Client, args: argparse.Namespace) -> int:
    data = client.pair(args.code, args.name)
    print("paired")
    _print("device_id", data["device_id"])
    _print("server", f"{data.get('name')} ({data['server_fp'][:16]}…)")
    _print("capabilities", ", ".join(data.get("caps", [])))
    _print("state file", client.state.path)
    return 0


def cmd_status(client: Client, _args: argparse.Namespace) -> int:
    data = client.call("GET", "/v1/status")
    _print("name", data.get("name"))
    _print("uptime_s", data.get("uptime_s"))
    session = data.get("session")
    _print(
        "session",
        f"{session['id']} {session['desktop']}/{session['type']} "
        f"{'LOCKED' if session['locked'] else 'unlocked'}"
        if session
        else "none",
    )
    for target in data.get("wake_targets", []):
        _print("wake target", f"{target['mac']} via {target['iface']} ({target['link']})")
    return 0


def cmd_unlock(client: Client, args: argparse.Namespace) -> int:
    data = client.call("POST", "/v1/unlock", {"session_id": args.session_id})
    _print("session", data["session_id"])
    _print("was_locked", data["was_locked"])
    _print("unlocked", data["unlocked"])
    return 0


def cmd_lock(client: Client, args: argparse.Namespace) -> int:
    data = client.call("POST", "/v1/lock", {"session_id": args.session_id})
    _print("session", data["session_id"])
    _print("was_locked", data["was_locked"])
    _print("locked", data["locked"])
    return 0


def cmd_wake(client: Client, args: argparse.Namespace) -> int:
    data = client.call("POST", "/v1/wake", {"target": args.target})
    for sent in data.get("sent", []):
        _print("sent", f"{sent['mac']} -> {sent['via']} ({sent['bytes']} bytes)")
    return 0


def _expect(label: str, expected_code: str, fn) -> bool:
    try:
        fn()
    except ApiFailure as exc:
        ok = exc.code == expected_code
        print(f"  [{'PASS' if ok else 'FAIL'}] {label:<34} -> {exc.status} {exc.code}")
        return ok
    print(f"  [FAIL] {label:<34} -> unexpectedly succeeded (wanted {expected_code})")
    return False


def cmd_replay(client: Client, _args: argparse.Namespace) -> int:
    nonce = b64u(secrets.token_bytes(16))
    timestamp = int(time.time())
    client.call("GET", "/v1/status", nonce=nonce, timestamp=timestamp)
    ok = _expect(
        "replayed nonce",
        "replayed_nonce",
        lambda: client.call("GET", "/v1/status", nonce=nonce, timestamp=timestamp),
    )
    return 0 if ok else 1


def cmd_tamper(client: Client, _args: argparse.Namespace) -> int:
    ok = _expect(
        "tampered body",
        "invalid_signature",
        lambda: client.call(
            "POST", "/v1/wake", {"target": "self"}, send_body=b'{"target":"self","evil":1}'
        ),
    )
    return 0 if ok else 1


def cmd_stale(client: Client, _args: argparse.Namespace) -> int:
    ok = _expect(
        "stale timestamp",
        "timestamp_out_of_window",
        lambda: client.call("GET", "/v1/status", timestamp=int(time.time()) - 3600),
    )
    return 0 if ok else 1


def cmd_selftest(client: Client, _args: argparse.Namespace) -> int:
    print("negative cases:")
    results = []

    nonce = b64u(secrets.token_bytes(16))
    timestamp = int(time.time())
    client.call("GET", "/v1/status", nonce=nonce, timestamp=timestamp)
    results.append(
        _expect("replayed nonce", "replayed_nonce",
                lambda: client.call("GET", "/v1/status", nonce=nonce, timestamp=timestamp))
    )
    results.append(
        _expect("stale timestamp", "timestamp_out_of_window",
                lambda: client.call("GET", "/v1/status", timestamp=int(time.time()) - 3600))
    )
    results.append(
        _expect("future timestamp", "timestamp_out_of_window",
                lambda: client.call("GET", "/v1/status", timestamp=int(time.time()) + 3600))
    )
    results.append(
        _expect("tampered body", "invalid_signature",
                lambda: client.call("POST", "/v1/wake", {"target": "self"},
                                    send_body=b'{"target":"self","evil":1}'))
    )
    results.append(
        _expect("wake MAC not allowlisted", "not_allowed",
                lambda: client.call("POST", "/v1/wake", {"target": "aa:bb:cc:dd:ee:ff"}))
    )
    results.append(
        _expect("broadcast outside LAN", "not_allowed",
                lambda: client.call("POST", "/v1/wake",
                                    {"target": client.state.data["wake"]["macs"][0],
                                     "broadcast": "8.8.8.8"}))
    )
    results.append(
        _expect("query string on signed route", "bad_request",
                lambda: client.call("GET", "/v1/status?admin=1"))
    )

    # A signature made with the wrong key must fail.
    saved = client.state.data["device_seed"]
    client.state.data["device_seed"] = secrets.token_bytes(32).hex()
    results.append(
        _expect("wrong signing key", "invalid_signature",
                lambda: client.call("GET", "/v1/status"))
    )
    client.state.data["device_seed"] = saved

    # A request signed against a different server's fingerprint must not verify
    # here -- this is the cross-server replay defence. We must stop checking the
    # response signature for this one case: we have deliberately replaced the
    # server key we would verify against, so the reply from the *real* server
    # would fail for the wrong reason and mask the result we are testing.
    saved_pub = client.state.data["server_pubkey"]
    other = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
    client.state.data["server_pubkey"] = b64u(other)
    client.verify_responses = False
    results.append(
        _expect("signed for another server", "invalid_signature",
                lambda: client.call("GET", "/v1/status"))
    )
    client.verify_responses = True
    client.state.data["server_pubkey"] = saved_pub

    print("\npositive cases:")
    data = client.call("GET", "/v1/status")
    print(f"  [PASS] status                             -> {data.get('name')}")
    results.append(True)

    passed = sum(1 for r in results if r)
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


COMMANDS = {
    "pair": cmd_pair,
    "status": cmd_status,
    "unlock": cmd_unlock,
    "lock": cmd_lock,
    "wake": cmd_wake,
    "replay": cmd_replay,
    "tamper": cmd_tamper,
    "stale": cmd_stale,
    "selftest": cmd_selftest,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    pair = sub.add_parser("pair")
    pair.add_argument("--code", required=True)
    pair.add_argument("--name", default=f"refclient@{socket.gethostname()}")

    unlock = sub.add_parser("unlock")
    unlock.add_argument("--session-id", default=None)

    lock = sub.add_parser("lock")
    lock.add_argument("--session-id", default=None)

    wake = sub.add_parser("wake")
    wake.add_argument("--target", default="self")

    for name in ("status", "replay", "tamper", "stale", "selftest"):
        sub.add_parser(name)

    args = parser.parse_args(argv)
    state = State(args.state)
    client = Client(state, args.host, args.port)

    try:
        return COMMANDS[args.command](client, args)
    except ApiFailure as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
