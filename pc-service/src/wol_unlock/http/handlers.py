"""Endpoint handlers.

Handlers return the ``data`` payload as a plain dict, or raise
:class:`~wol_unlock.errors.ApiError`. The envelope middleware wraps and signs
whatever comes back, so no handler can accidentally emit an unsigned response.
"""

from __future__ import annotations

import ipaddress
import json
from typing import Any

from aiohttp import web

from .. import session as session_mod
from .. import wake as wake_mod
from ..context import ServiceContext
from ..errors import ApiError
from .middleware import APP_CONTEXT, signed


def _context(request: web.Request) -> ServiceContext:
    return request.app[APP_CONTEXT]


async def _json_body(request: web.Request, *, allow_empty: bool = True) -> dict[str, Any]:
    raw = await request.read()
    if not raw:
        if allow_empty:
            return {}
        raise ApiError("bad_request", "a JSON body is required")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ApiError("bad_request", "body is not valid JSON") from exc
    if not isinstance(data, dict):
        raise ApiError("bad_request", "body must be a JSON object")
    return data


def _optional_str(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError("bad_request", f"{key} must be a string or null")
    return value


def _require_str(data: dict[str, Any], key: str, *, max_len: int = 256) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ApiError("bad_request", f"{key} is required and must be a non-empty string")
    if len(value) > max_len:
        raise ApiError("bad_request", f"{key} is too long")
    return value


# --------------------------------------------------------------------------- #
# GET /v1/server-info  (unauthenticated)
# --------------------------------------------------------------------------- #

async def server_info(request: web.Request) -> dict[str, Any]:
    return _context(request).server_info()


# --------------------------------------------------------------------------- #
# POST /v1/pair  (pairing code + proof)
# --------------------------------------------------------------------------- #

async def pair(request: web.Request) -> dict[str, Any]:
    ctx = _context(request)
    data = await _json_body(request, allow_empty=False)

    version = data.get("v", 1)
    if version != 1:
        raise ApiError("bad_request", f"unsupported pairing version {version!r}")

    record = await ctx.pairing.submit(
        code=_require_str(data, "code", max_len=32),
        device_pubkey_b64=_require_str(data, "device_pubkey", max_len=64),
        proof_b64=_require_str(data, "proof", max_len=128),
        device_name=_optional_str(data, "device_name") or "Unnamed device",
        platform=_optional_str(data, "platform") or "",
    )

    payload: dict[str, Any] = {
        "device_id": record.device_id,
        "server_pubkey": ctx.identity.public_b64,
        "server_fp": ctx.identity.fingerprint,
        "name": ctx.config.name,
        "api": 1,
        "caps": list(ctx.config.capabilities),
    }
    if ctx.config.wake_targets:
        payload["wake"] = {
            "macs": [t.mac for t in ctx.config.wake_targets],
            "broadcast": ctx.config.wake_targets[0].broadcast,
            "port": ctx.config.wake_targets[0].port,
        }
    return payload


# --------------------------------------------------------------------------- #
# GET /v1/status  (signed)
# --------------------------------------------------------------------------- #

@signed
async def status(request: web.Request) -> dict[str, Any]:
    ctx = _context(request)
    current = await session_mod.current_session()
    return {
        **ctx.server_info(),
        "uptime_s": ctx.uptime_s,
        "session": current.to_dict() if current else None,
        "wake_targets": wake_mod.describe_targets(ctx.config.wake_targets),
        "pairing": ctx.pairing.snapshot(),
    }


# --------------------------------------------------------------------------- #
# POST /v1/wake  (signed)
# --------------------------------------------------------------------------- #

@signed
async def wake(request: web.Request) -> dict[str, Any]:
    ctx = _context(request)
    data = await _json_body(request)

    target_spec = _optional_str(data, "target") or "self"

    if target_spec == "self":
        targets = list(ctx.config.wake_targets)
        if not targets:
            raise ApiError("wake_failed", "no wake targets are configured")
    else:
        target = ctx.config.wake_target_for(target_spec)
        if target is None:
            raise ApiError(
                "not_allowed",
                "that MAC is not in the configured wake allowlist",
            )
        targets = [_apply_overrides(ctx, target, data)]

    results = await wake_mod.send_to_targets(targets)
    return {"sent": [result.to_dict() for result in results]}


def _apply_overrides(ctx: ServiceContext, target: Any, data: dict[str, Any]) -> Any:
    """Honour caller-supplied broadcast/port, within limits.

    A broadcast override must land inside an allowed network. Without that check
    this endpoint would be a signed relay for spraying UDP at arbitrary hosts.
    """
    from dataclasses import replace

    broadcast = _optional_str(data, "broadcast")
    port = data.get("port")

    if broadcast is not None:
        try:
            addr = ipaddress.IPv4Address(broadcast)
        except ValueError as exc:
            raise ApiError("bad_request", "broadcast must be an IPv4 address") from exc
        if not any(addr in net for net in ctx.config.http.allowed_networks):
            raise ApiError(
                "not_allowed", "broadcast address is outside the allowed networks"
            )
        target = replace(target, broadcast=str(addr))

    if port is not None:
        if not isinstance(port, int) or isinstance(port, bool) or not (1 <= port <= 65535):
            raise ApiError("bad_request", "port must be an integer in 1-65535")
        target = replace(target, port=port)

    return target


# --------------------------------------------------------------------------- #
# POST /v1/unlock  (signed)
# --------------------------------------------------------------------------- #

@signed
async def unlock(request: web.Request) -> dict[str, Any]:
    ctx = _context(request)
    if not ctx.config.unlock_enabled:
        raise ApiError("not_allowed", "unlocking is disabled in the configuration")

    data = await _json_body(request)
    session_id = _optional_str(data, "session_id")

    result = await session_mod.unlock_session(session_id)
    return result.to_dict()


# --------------------------------------------------------------------------- #
# POST /v1/lock  (signed)
# --------------------------------------------------------------------------- #

@signed
async def lock(request: web.Request) -> dict[str, Any]:
    ctx = _context(request)
    if not ctx.config.lock_enabled:
        raise ApiError("not_allowed", "locking is disabled in the configuration")

    data = await _json_body(request)
    session_id = _optional_str(data, "session_id")

    # Not `unlock_session`'s target: locking wants the session that is *not*
    # already locked. See PROTOCOL.md 6.2.
    result = await session_mod.lock_session(session_id)
    return result.to_dict()
