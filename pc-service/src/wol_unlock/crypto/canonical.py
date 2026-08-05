"""Canonical byte strings that get signed, and the encodings around them.

This module is the single place where the v1 signing formats are written on the
Python side; ``mobile/src/crypto/canonical.ts`` is its mirror. Changing anything
here is a protocol break and must be matched in PROTOCOL.md, in the TypeScript
mirror, and in the test vectors.

Design notes:

* Fields are newline-separated with no length prefixes. That is only safe because
  every interpolated field is drawn from a charset that cannot contain a newline,
  which :func:`_field` enforces at runtime rather than by convention.
* Each construction carries a distinct domain tag on line 1, so a signature made
  for one purpose cannot be presented as another.
"""

from __future__ import annotations

import base64
import hashlib
import re

DOMAIN_REQUEST = "wol-unlock/v1/request"
DOMAIN_RESPONSE = "wol-unlock/v1/response"
DOMAIN_PAIR = "wol-unlock/v1/pair"

NONCE_BYTES = 16
NONCE_CHARS = 22  # b64u(16 bytes)
SIGNATURE_BYTES = 64
PUBKEY_BYTES = 32
DEVICE_ID_CHARS = 22  # b64u(16 bytes)
FINGERPRINT_CHARS = 43  # b64u(32 bytes)

_B64U_RE = re.compile(r"^[A-Za-z0-9_-]*$")


def b64u_encode(raw: bytes) -> str:
    """base64url without padding."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def b64u_decode(text: str, *, expect_len: int | None = None) -> bytes:
    """Strict base64url decode.

    Rejects padding characters, non-alphabet bytes, impossible lengths, and
    non-canonical encodings (trailing bits set that a correct encoder would have
    zeroed). Strictness matters here: a lenient decoder lets the same key or
    signature be spelled several ways, which turns identifiers into a set rather
    than a value and breaks the uniqueness the nonce and device tables rely on.
    """
    if not isinstance(text, str) or not _B64U_RE.match(text):
        raise ValueError("not base64url")
    pad = (-len(text)) % 4
    if pad == 3:
        raise ValueError("impossible base64url length")
    try:
        raw = base64.urlsafe_b64decode(text + "=" * pad)
    except Exception as exc:  # noqa: BLE001 - binascii raises several types
        raise ValueError("malformed base64url") from exc
    if expect_len is not None and len(raw) != expect_len:
        raise ValueError(f"expected {expect_len} bytes, got {len(raw)}")
    if b64u_encode(raw) != text:
        raise ValueError("non-canonical base64url")
    return raw


def sha256_b64u(data: bytes) -> str:
    """b64u(SHA-256(data)) -- the body-hash form used in canonical strings."""
    return b64u_encode(hashlib.sha256(data).digest())


def fingerprint(pubkey_raw: bytes) -> str:
    """Public identity of a key: b64u(SHA-256(pubkey)), 43 chars."""
    if len(pubkey_raw) != PUBKEY_BYTES:
        raise ValueError("public key must be 32 raw bytes")
    return b64u_encode(hashlib.sha256(pubkey_raw).digest())


def device_id_for(pubkey_raw: bytes) -> str:
    """Device identifier: b64u(SHA-256(pubkey)[:16]), 22 chars.

    Always derived server-side from the enrolled key, never accepted from a
    client, so a device cannot claim another device's record.
    """
    if len(pubkey_raw) != PUBKEY_BYTES:
        raise ValueError("public key must be 32 raw bytes")
    return b64u_encode(hashlib.sha256(pubkey_raw).digest()[:16])


def _field(name: str, value: object) -> str:
    """Stringify one canonical field, refusing anything containing a newline."""
    text = str(value)
    if "\n" in text or "\r" in text:
        raise ValueError(f"canonical field {name!r} contains a newline")
    return text


def canonical_request(
    *,
    method: str,
    path: str,
    timestamp: int | str,
    nonce: str,
    body_sha256: str,
    device_id: str,
    server_fp: str,
) -> bytes:
    """Bytes the *device* signs for an authenticated request (PROTOCOL.md 2.1)."""
    parts = (
        DOMAIN_REQUEST,
        _field("method", method).upper(),
        _field("path", path),
        _field("timestamp", timestamp),
        _field("nonce", nonce),
        _field("body_sha256", body_sha256),
        _field("device_id", device_id),
        _field("server_fp", server_fp),
    )
    return ("\n".join(parts) + "\n").encode("ascii")


def canonical_response(
    *,
    status: int | str,
    nonce_echo: str,
    body_sha256: str,
    server_fp: str,
) -> bytes:
    """Bytes the *server* signs for a response (PROTOCOL.md 2.2).

    ``nonce_echo`` is the empty string for requests that never carried a nonce.
    The line is still emitted so the field count never varies.
    """
    parts = (
        DOMAIN_RESPONSE,
        _field("status", status),
        _field("nonce_echo", nonce_echo),
        _field("body_sha256", body_sha256),
        _field("server_fp", server_fp),
    )
    return ("\n".join(parts) + "\n").encode("ascii")


def canonical_pair(*, code: str, device_pubkey_b64: str, server_fp: str) -> bytes:
    """Bytes the enrolling *device* signs as its pairing proof (PROTOCOL.md 2.3)."""
    parts = (
        DOMAIN_PAIR,
        _field("code", code).upper(),
        _field("device_pubkey", device_pubkey_b64),
        _field("server_fp", server_fp),
    )
    return ("\n".join(parts) + "\n").encode("ascii")
