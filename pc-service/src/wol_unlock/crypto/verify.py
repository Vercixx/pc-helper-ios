"""Parsing and verification of signed request material.

Kept free of aiohttp and SQLite so the whole verification path is testable with
plain dicts and bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ..errors import ApiError
from . import canonical as C

HEADER_VERSION = "X-WU-Version"
HEADER_DEVICE = "X-WU-Device"
HEADER_TIMESTAMP = "X-WU-Timestamp"
HEADER_NONCE = "X-WU-Nonce"
HEADER_SIGNATURE = "X-WU-Signature"
HEADER_SERVER_SIGNATURE = "X-WU-Server-Signature"

SUPPORTED_VERSION = 1


@dataclass(frozen=True, slots=True)
class SignedRequestHeaders:
    """The five auth headers, syntactically validated but not yet trusted."""

    version: int
    device_id: str
    timestamp: int
    nonce: str
    signature: bytes


def parse_auth_headers(headers: Mapping[str, str]) -> SignedRequestHeaders:
    """Validate header syntax.

    Raises ``bad_request`` for anything malformed. Nothing here consults the
    device table or the clock -- this is pure shape checking, so that a garbage
    request is rejected before it can touch storage.
    """

    def need(name: str) -> str:
        value = headers.get(name)
        if value is None:
            raise ApiError("bad_request", f"missing {name} header")
        return value.strip()

    raw_version = need(HEADER_VERSION)
    if not raw_version.isdigit():
        raise ApiError("bad_request", f"{HEADER_VERSION} must be an integer")
    version = int(raw_version)
    if version != SUPPORTED_VERSION:
        raise ApiError("bad_request", f"unsupported protocol version {version}")

    device_id = need(HEADER_DEVICE)
    if len(device_id) != C.DEVICE_ID_CHARS:
        raise ApiError("bad_request", "malformed device id")
    try:
        C.b64u_decode(device_id, expect_len=16)
    except ValueError as exc:
        raise ApiError("bad_request", "malformed device id") from exc

    raw_ts = need(HEADER_TIMESTAMP)
    # Reject '+1754390000', ' 1754390000', '01754390000' and similar: the signed
    # canonical string contains one exact spelling, so accepting variants here
    # would let the same instant be presented several ways.
    if not raw_ts.isdigit() or (len(raw_ts) > 1 and raw_ts[0] == "0"):
        raise ApiError("bad_request", "malformed timestamp")
    timestamp = int(raw_ts)

    nonce = need(HEADER_NONCE)
    if len(nonce) != C.NONCE_CHARS:
        raise ApiError("bad_request", "malformed nonce")
    try:
        C.b64u_decode(nonce, expect_len=C.NONCE_BYTES)
    except ValueError as exc:
        raise ApiError("bad_request", "malformed nonce") from exc

    try:
        signature = C.b64u_decode(need(HEADER_SIGNATURE), expect_len=C.SIGNATURE_BYTES)
    except ValueError as exc:
        raise ApiError("bad_request", "malformed signature") from exc

    return SignedRequestHeaders(
        version=version,
        device_id=device_id,
        timestamp=timestamp,
        nonce=nonce,
        signature=signature,
    )


def check_timestamp(timestamp: int, now: int, skew_s: int) -> None:
    """Reject requests outside the freshness window (symmetric, so a phone whose
    clock runs slightly fast is not locked out)."""
    if abs(now - timestamp) > skew_s:
        raise ApiError(
            "timestamp_out_of_window",
            f"timestamp differs from server clock by {abs(now - timestamp)}s (max {skew_s}s)",
        )


def verify_signature(pubkey_raw: bytes, message: bytes, signature: bytes) -> None:
    """Ed25519 verification, raising ``invalid_signature`` on any failure."""
    try:
        Ed25519PublicKey.from_public_bytes(pubkey_raw).verify(signature, message)
    except (InvalidSignature, ValueError) as exc:
        raise ApiError("invalid_signature", "signature verification failed") from exc


def verify_request_signature(
    *,
    pubkey_raw: bytes,
    method: str,
    path: str,
    timestamp: int,
    nonce: str,
    body: bytes,
    device_id: str,
    server_fp: str,
    signature: bytes,
    expected_body_sha256: str | None = None,
) -> None:
    """Rebuild the canonical request from what was actually received and verify.

    The body hash is recomputed from the received bytes rather than taken from
    the request, so a body that does not match what was signed fails here even if
    the signature itself is well-formed.
    """
    body_hash = C.sha256_b64u(body)
    if expected_body_sha256 is not None and body_hash != expected_body_sha256:
        raise ApiError("body_hash_mismatch", "request body does not match its signed hash")
    message = C.canonical_request(
        method=method,
        path=path,
        timestamp=timestamp,
        nonce=nonce,
        body_sha256=body_hash,
        device_id=device_id,
        server_fp=server_fp,
    )
    verify_signature(pubkey_raw, message, signature)
