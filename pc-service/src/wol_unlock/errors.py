"""Error taxonomy shared by the HTTP layer and everything beneath it.

Codes and their HTTP mappings are normative -- see PROTOCOL.md section 4.1. The
mapping lives here rather than in the HTTP layer so that non-HTTP callers (the
control socket, the CLI) surface the same vocabulary.
"""

from __future__ import annotations

# code -> HTTP status
ERROR_STATUS: dict[str, int] = {
    "bad_request": 400,
    "forbidden_network": 403,
    "unknown_device": 401,
    "device_revoked": 403,
    "timestamp_out_of_window": 401,
    "replayed_nonce": 401,
    "body_hash_mismatch": 401,
    "invalid_signature": 401,
    "rate_limited": 429,
    "pairing_disabled": 409,
    "invalid_code": 401,
    "pairing_expired": 409,
    "pairing_denied": 403,
    "pairing_timeout": 409,
    "no_session": 409,
    "unlock_failed": 500,
    "lock_failed": 500,
    "wake_failed": 500,
    "not_allowed": 403,
    "internal_error": 500,
}


class ApiError(Exception):
    """An error with a stable machine-readable code.

    ``message`` is for humans and logs. It is returned to the client because the
    threat model is a LAN peer who already knows what this service is; withholding
    detail would cost debuggability without buying secrecy.
    """

    __slots__ = ("code", "message", "status")

    def __init__(self, code: str, message: str = "", status: int | None = None) -> None:
        if code not in ERROR_STATUS and status is None:
            raise ValueError(f"unknown error code {code!r} and no explicit status")
        self.code = code
        self.message = message or code.replace("_", " ")
        self.status = status if status is not None else ERROR_STATUS[code]
        super().__init__(f"{code}: {self.message}")

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class ConfigError(Exception):
    """Raised at startup for an invalid configuration file.

    Always fatal: a service that guesses at what a malformed security-relevant
    setting meant is worse than one that refuses to start.
    """
