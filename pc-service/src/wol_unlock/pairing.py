"""The pairing window: the only path by which a new device becomes trusted.

Security properties this module is responsible for (PROTOCOL.md 9):

* A window can only be opened from the control socket, which is 0600 in the
  user's runtime directory and checks ``SO_PEERCRED``. There is no network route
  to :meth:`PairingManager.begin`, so pairing requires local access to the machine
  by construction rather than by policy.
* At most one window, at most one in-flight enrollment.
* The code is single-use and destroyed on success *and* on denial.
* Expiry is measured on a monotonic clock, so changing the wall clock cannot
  extend a window.
* A wrong code costs one of three attempts; exhausting them closes the window.
* The code never reaches the log or the audit table.
"""

from __future__ import annotations

import asyncio
import enum
import hashlib
import hmac
import secrets
import socket
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable

from .config import Config
from .crypto import canonical as C
from .crypto.verify import verify_signature
from .errors import ApiError
from .identity import ServerIdentity
from .store import DeviceRecord, Store

# Crockford base32 minus I, L, O and U: no character can be confused for another
# when read off a screen and typed on a phone.
CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LENGTH = 8

# Applied to typed input so a misread code still works.
_FOLD = str.maketrans({"I": "1", "L": "1", "O": "0", "U": "V"})

Listener = Callable[[str, dict[str, Any]], None]


class PairingState(str, enum.Enum):
    IDLE = "idle"
    OPEN = "open"
    AWAITING_APPROVAL = "awaiting_approval"


def generate_code() -> str:
    """8 characters from a 32-symbol alphabet: 40 bits of entropy.

    Brute force is bounded by the 120-second window, the three-attempt limit and
    the rate limiter rather than by entropy alone -- but 40 bits means an
    attacker who somehow bypassed all three still gets nowhere.
    """
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(value: str) -> str:
    """Upper-case, strip grouping punctuation, fold look-alike characters."""
    cleaned = "".join(ch for ch in str(value).upper() if ch.isalnum())
    return cleaned.translate(_FOLD)


def format_code(code: str) -> str:
    """``K7M2QX4B`` -> ``K7M2-QX4B`` for display only."""
    return f"{code[:4]}-{code[4:]}" if len(code) == CODE_LENGTH else code


def _hash_code(code: str) -> bytes:
    return hashlib.sha256(f"wol-unlock/v1/code\n{code}\n".encode()).digest()


def build_qr_payload(config: Config, identity: ServerIdentity, code: str) -> str:
    """The ``wolunlock:1?...`` URI encoded into the terminal QR (PROTOCOL.md 8.1)."""
    host = f"{socket.gethostname().split('.')[0]}.local"
    params = {
        "n": config.name,
        "h": host,
        "p": str(config.http.port),
        "f": identity.fingerprint,
        "c": code,
    }
    if config.wake_targets:
        params["m"] = ",".join(t.mac.replace(":", "") for t in config.wake_targets)
        params["b"] = config.wake_targets[0].broadcast
    return "wolunlock:1?" + urllib.parse.urlencode(params)


@dataclass(slots=True)
class PendingEnrollment:
    """A device that presented a valid code and is awaiting local approval."""

    device_id: str
    pubkey: bytes
    fingerprint: str
    device_name: str
    platform: str
    requested_at: float
    decision: asyncio.Future[bool]

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "fp": self.fingerprint,
            "short_fp": self.fingerprint[:8],
            "device_name": self.device_name,
            "platform": self.platform,
            "requested_at": int(self.requested_at),
        }


@dataclass(slots=True)
class OpenWindow:
    code_hash: bytes
    opened_at: float
    deadline_monotonic: float
    expires_at_wall: int
    attempts_left: int
    qr_payload: str
    code_for_display: str


class PairingManager:
    """Owns the pairing window and its state transitions."""

    def __init__(self, config: Config, identity: ServerIdentity, store: Store) -> None:
        self._config = config
        self._identity = identity
        self._store = store
        self._lock = asyncio.Lock()
        self._state = PairingState.IDLE
        self._window: OpenWindow | None = None
        self._pending: PendingEnrollment | None = None
        self._listeners: list[Listener] = []
        self._expiry_task: asyncio.Task[None] | None = None

    # -- listeners ---------------------------------------------------------- #

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        try:
            self._listeners.remove(listener)
        except ValueError:
            pass

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        for listener in list(self._listeners):
            try:
                listener(event, data)
            except Exception:  # noqa: BLE001 - a broken CLI must not break pairing
                pass

    # -- introspection ------------------------------------------------------ #

    @property
    def state(self) -> PairingState:
        return self._state

    @property
    def is_open(self) -> bool:
        return self._state is not PairingState.IDLE

    def snapshot(self) -> dict[str, Any]:
        """Status for the API and the CLI. Never includes the code itself."""
        data: dict[str, Any] = {"active": self.is_open, "state": self._state.value}
        if self._window is not None:
            remaining = max(0, int(self._window.deadline_monotonic - _monotonic()))
            data.update(
                {
                    "expires_at": self._window.expires_at_wall,
                    "expires_in_s": remaining,
                    "attempts_left": self._window.attempts_left,
                }
            )
        if self._pending is not None:
            data["pending"] = self._pending.to_dict()
        return data

    # -- window lifecycle --------------------------------------------------- #

    async def begin(self, window_s: int | None = None) -> dict[str, Any]:
        """Open a pairing window. Refuses if one is already open."""
        async with self._lock:
            if self._state is not PairingState.IDLE:
                raise ApiError(
                    "pairing_disabled",
                    "a pairing window is already open; cancel it first",
                )
            window_s = int(window_s or self._config.pairing.window_s)
            if not (15 <= window_s <= 600):
                raise ApiError("bad_request", "pairing window must be 15-600 seconds")

            code = generate_code()
            now_wall = int(time.time())
            self._window = OpenWindow(
                code_hash=_hash_code(code),
                opened_at=_monotonic(),
                deadline_monotonic=_monotonic() + window_s,
                expires_at_wall=now_wall + window_s,
                attempts_left=self._config.pairing.max_attempts,
                qr_payload=build_qr_payload(self._config, self._identity, code),
                code_for_display=code,
            )
            self._state = PairingState.OPEN
            self._schedule_expiry(window_s)

            payload = {
                "code": code,
                "code_display": format_code(code),
                "qr": self._window.qr_payload,
                "expires_at": self._window.expires_at_wall,
                "expires_in_s": window_s,
                "server_fp": self._identity.fingerprint,
                "require_approval": self._config.pairing.require_approval,
            }

        self._emit("pair.opened", {k: v for k, v in payload.items() if k != "code"})
        return payload

    async def cancel(self, reason: str = "cancelled") -> None:
        async with self._lock:
            self._close_locked(reason)

    def _close_locked(self, reason: str) -> None:
        """Tear the window down. Callers must hold the lock."""
        if self._expiry_task is not None:
            self._expiry_task.cancel()
            self._expiry_task = None
        pending, self._pending = self._pending, None
        self._window = None
        self._state = PairingState.IDLE
        if pending is not None and not pending.decision.done():
            pending.decision.set_result(False)
        self._emit("pair.closed", {"reason": reason})

    def _schedule_expiry(self, window_s: int) -> None:
        async def expire() -> None:
            try:
                await asyncio.sleep(window_s)
            except asyncio.CancelledError:
                return
            async with self._lock:
                # Only expire a window that is still merely OPEN. An enrollment
                # already parked for approval gets to finish on its own timer;
                # yanking it here would deny a device the operator is mid-way
                # through approving.
                if self._state is PairingState.OPEN:
                    self._close_locked("expired")

        self._expiry_task = asyncio.create_task(expire())

    # -- enrollment --------------------------------------------------------- #

    async def submit(
        self,
        *,
        code: str,
        device_pubkey_b64: str,
        proof_b64: str,
        device_name: str,
        platform: str,
    ) -> DeviceRecord:
        """Validate an enrollment attempt and, once approved, store the device.

        Blocks while the operator decides, up to ``approval_timeout_s``.
        """
        try:
            pubkey = C.b64u_decode(device_pubkey_b64, expect_len=C.PUBKEY_BYTES)
        except ValueError as exc:
            raise ApiError("bad_request", "malformed device_pubkey") from exc
        try:
            proof = C.b64u_decode(proof_b64, expect_len=C.SIGNATURE_BYTES)
        except ValueError as exc:
            raise ApiError("bad_request", "malformed proof") from exc

        supplied = normalize_code(code)
        pending: PendingEnrollment

        async with self._lock:
            if self._state is PairingState.AWAITING_APPROVAL:
                raise ApiError(
                    "pairing_disabled", "another device is already awaiting approval"
                )
            if self._state is not PairingState.OPEN or self._window is None:
                raise ApiError("pairing_disabled", "no pairing window is open")

            window = self._window
            if _monotonic() >= window.deadline_monotonic:
                self._close_locked("expired")
                raise ApiError("pairing_expired", "the pairing window has expired")

            if not hmac.compare_digest(_hash_code(supplied), window.code_hash):
                window.attempts_left -= 1
                remaining = window.attempts_left
                if remaining <= 0:
                    self._close_locked("too_many_attempts")
                    raise ApiError(
                        "invalid_code", "incorrect code; the pairing window is now closed"
                    )
                raise ApiError(
                    "invalid_code", f"incorrect code; {remaining} attempt(s) remaining"
                )

            # The code was right. Now prove the device holds the private key for
            # the public key it is enrolling, bound to this code and this server.
            message = C.canonical_pair(
                code=supplied,
                device_pubkey_b64=C.b64u_encode(pubkey),
                server_fp=self._identity.fingerprint,
            )
            try:
                verify_signature(pubkey, message, proof)
            except ApiError:
                self._close_locked("bad_proof")
                # A correct code paired with a bad proof means the code leaked to
                # someone who does not control the key. Burn the window.
                raise ApiError(
                    "invalid_signature",
                    "pairing proof did not verify; the window has been closed",
                ) from None

            device_id = C.device_id_for(pubkey)
            pending = PendingEnrollment(
                device_id=device_id,
                pubkey=pubkey,
                fingerprint=C.fingerprint(pubkey),
                device_name=_clean_name(device_name),
                platform=_clean_platform(platform),
                requested_at=time.time(),
                decision=asyncio.get_running_loop().create_future(),
            )

            if not self._config.pairing.require_approval:
                return await self._finish_locked(pending)

            self._pending = pending
            self._state = PairingState.AWAITING_APPROVAL

        self._emit("pair.request", pending.to_dict())

        try:
            approved = await asyncio.wait_for(
                pending.decision, timeout=self._config.pairing.approval_timeout_s
            )
        except asyncio.TimeoutError:
            async with self._lock:
                self._close_locked("approval_timeout")
            raise ApiError(
                "pairing_timeout", "no response from the operator at the PC"
            ) from None

        async with self._lock:
            if not approved:
                self._close_locked("denied")
                raise ApiError("pairing_denied", "the operator declined this device")
            return await self._finish_locked(pending)

    async def _finish_locked(self, pending: PendingEnrollment) -> DeviceRecord:
        """Persist the device and close the window. Callers must hold the lock."""
        record = await self._store.upsert_device(
            device_id=pending.device_id,
            pubkey=pending.pubkey,
            name=pending.device_name,
            platform=pending.platform,
            now=int(time.time()),
        )
        await self._store.add_audit(
            ts=int(time.time()),
            action="pair",
            result="ok",
            device_id=record.device_id,
            detail=f"{record.name} ({pending.fingerprint[:8]})",
        )
        # Announce the success before tearing the window down, so a CLI watching
        # the event stream sees "completed" and not just a bare "closed".
        self._emit("pair.completed", record.to_dict())
        self._close_locked("paired")
        return record

    async def resolve(self, approved: bool) -> bool:
        """Answer a parked enrollment from the control socket."""
        async with self._lock:
            if self._state is not PairingState.AWAITING_APPROVAL or self._pending is None:
                return False
            if self._pending.decision.done():
                return False
            self._pending.decision.set_result(approved)
            return True

    async def shutdown(self) -> None:
        async with self._lock:
            if self._state is not PairingState.IDLE:
                self._close_locked("shutdown")


def _monotonic() -> float:
    return time.monotonic()


def _clean_name(value: str) -> str:
    name = " ".join(str(value or "").split())[:64]
    return name or "Unnamed device"


def _clean_platform(value: str) -> str:
    cleaned = "".join(ch for ch in str(value or "").lower() if ch.isalnum() or ch in "-_")
    return cleaned[:16]
