"""The middleware chain.

Order matters and is asserted by tests. Outermost first:

1. :func:`envelope_middleware` -- turns whatever happened into a signed JSON
   envelope. It is outermost so that *every* response, including 404s, 405s,
   rate-limit rejections and unhandled exceptions, carries a server signature. A
   client that requires the signature can therefore never be fooled by an
   unsigned error injected on the wire.
2. :func:`network_middleware` -- drops peers outside the configured CIDRs before
   anything else runs.
3. :func:`ratelimit_middleware` -- token bucket per source IP.
4. :func:`auth_middleware` -- signature verification for routes marked ``@signed``.

Steps 2-4 return whatever the inner handler returned (a plain ``dict``); only the
envelope middleware constructs a ``web.Response``.
"""

from __future__ import annotations

import json
import time
from typing import Any, Awaitable, Callable

from aiohttp import web

from ..context import ServiceContext
from ..crypto import canonical as C
from ..crypto import verify as V
from ..errors import ApiError
from ..store import DeviceRecord

Handler = Callable[[web.Request], Awaitable[Any]]

REQUIRES_AUTH = "__wu_requires_auth__"

#: The complete set of endpoints reachable without a signature. Authentication is
#: decided by *exclusion* from this set, never by the presence of a decorator, so
#: that a new endpoint added without any annotation is protected by default. The
#: @signed decorator below is a readability aid that :func:`build_app`
#: cross-checks against this set at startup.
PUBLIC_PATHS = frozenset({"/v1/server-info", "/v1/pair"})

#: Application key holding the assembled service.
APP_CONTEXT: web.AppKey[ServiceContext] = web.AppKey("wu_context", ServiceContext)
#: Request key holding the nonce to echo in the response signature.
KEY_NONCE: web.RequestKey[str] = web.RequestKey("wu_nonce", str)
#: Request key holding the verified device, once authentication has succeeded.
KEY_DEVICE: web.RequestKey[DeviceRecord] = web.RequestKey("wu_device", DeviceRecord)


def signed(handler: Handler) -> Handler:
    """Annotate a handler as requiring a verified signature."""
    setattr(handler, REQUIRES_AUTH, True)
    return handler


def _requires_auth(request: web.Request) -> bool:
    """Whether this request must carry a valid signature.

    Note the explicit ``is None`` checks. ``UrlMappingMatchInfo`` subclasses
    ``dict``, and a route with no path variables produces an *empty* one -- so a
    truthiness test here silently exempts every fixed path from authentication.
    """
    match_info = request.match_info
    if match_info is None:
        return False
    # No route matched: let aiohttp's own 404/405 handler run and be enveloped,
    # rather than answering "missing auth header" for a path that does not exist.
    if match_info.http_exception is not None:
        return False
    return request.path not in PUBLIC_PATHS


def _context(request: web.Request) -> ServiceContext:
    return request.app[APP_CONTEXT]


def _peer_ip(request: web.Request) -> str:
    """The transport peer address.

    ``X-Forwarded-For`` is deliberately ignored. This service is meant to be
    reached directly on the LAN; honouring a forwarding header would let any
    client claim any source address and walk straight through the CIDR allowlist.
    """
    return request.remote or ""


# --------------------------------------------------------------------------- #
# 1. Envelope + response signing
# --------------------------------------------------------------------------- #

def _extract_nonce_echo(request: web.Request) -> str:
    """The nonce to echo in the response signature.

    Taken straight from the request headers rather than from the authenticated
    context, because a response must be verifiable even when it was rejected
    *before* authentication ran -- a rate limit, a network-allowlist refusal, a
    query string on a signed route. Signing those with an empty echo would leave
    the client unable to verify precisely the errors it most needs to trust.

    Echoing an attacker-supplied value costs nothing: it is not a secret, and the
    response construction is domain-separated from every other signed string.
    """
    value = (request.headers.get(V.HEADER_NONCE) or "").strip()
    if len(value) != C.NONCE_CHARS:
        return ""
    try:
        C.b64u_decode(value, expect_len=C.NONCE_BYTES)
    except ValueError:
        return ""
    return value


@web.middleware
async def envelope_middleware(request: web.Request, handler: Handler) -> web.StreamResponse:
    ctx = _context(request)
    request[KEY_NONCE] = _extract_nonce_echo(request)
    try:
        result = await handler(request)
        status = 200
        payload: dict[str, Any] = {
            "ok": True,
            "ts": int(time.time()),
            "data": result if result is not None else {},
        }
    except ApiError as exc:
        status = exc.status
        payload = {"ok": False, "ts": int(time.time()), "error": exc.to_dict()}
    except web.HTTPException as exc:
        mapped = _map_http_exception(exc)
        status = mapped.status
        payload = {"ok": False, "ts": int(time.time()), "error": mapped.to_dict()}
    except Exception as exc:  # noqa: BLE001 - nothing may escape unsigned
        request.app.logger.exception("unhandled error serving %s", request.path)
        status = 500
        payload = {
            "ok": False,
            "ts": int(time.time()),
            "error": {"code": "internal_error", "message": type(exc).__name__},
        }

    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    signature = ctx.identity.sign(
        C.canonical_response(
            status=status,
            nonce_echo=request.get(KEY_NONCE, ""),
            body_sha256=C.sha256_b64u(body),
            server_fp=ctx.identity.fingerprint,
        )
    )

    await _audit(request, payload)

    return web.Response(
        status=status,
        body=body,
        content_type="application/json",
        charset="utf-8",
        headers={
            V.HEADER_SERVER_SIGNATURE: C.b64u_encode(signature),
            "X-WU-Server-Fp": ctx.identity.fingerprint,
            "Cache-Control": "no-store",
        },
    )


def _map_http_exception(exc: web.HTTPException) -> ApiError:
    if exc.status == 404:
        return ApiError("bad_request", "no such endpoint", status=404)
    if exc.status == 405:
        return ApiError("bad_request", "method not allowed", status=405)
    if exc.status == 413:
        return ApiError("bad_request", "request body too large", status=413)
    if 400 <= exc.status < 500:
        return ApiError("bad_request", exc.reason or "bad request", status=exc.status)
    return ApiError("internal_error", exc.reason or "server error", status=exc.status)


async def _audit(request: web.Request, payload: dict[str, Any]) -> None:
    """Record the outcome of every request except unauthenticated discovery.

    ``/v1/server-info`` is skipped: it is the endpoint a scanner hits repeatedly
    and logging it would drown the interesting rows in noise.
    """
    if request.path in ("/v1/server-info", "/"):
        return
    ctx = _context(request)
    device = request.get(KEY_DEVICE)
    result = "ok" if payload.get("ok") else str(payload.get("error", {}).get("code", "error"))
    try:
        await ctx.store.add_audit(
            ts=int(time.time()),
            action=f"{request.method} {request.path}",
            result=result,
            device_id=device.device_id if device is not None else None,
            peer_ip=_peer_ip(request),
            detail=None if payload.get("ok") else payload.get("error", {}).get("message"),
        )
    except Exception:  # noqa: BLE001 - auditing must never break a response
        request.app.logger.warning("failed to write audit row", exc_info=True)


# --------------------------------------------------------------------------- #
# 2. Network allowlist
# --------------------------------------------------------------------------- #

@web.middleware
async def network_middleware(request: web.Request, handler: Handler) -> Any:
    ctx = _context(request)
    peer = _peer_ip(request)
    if not ctx.config.http.allows(peer):
        raise ApiError(
            "forbidden_network", f"source address {peer or 'unknown'} is not on the local network"
        )
    return await handler(request)


# --------------------------------------------------------------------------- #
# 3. Rate limiting
# --------------------------------------------------------------------------- #

@web.middleware
async def ratelimit_middleware(request: web.Request, handler: Handler) -> Any:
    ctx = _context(request)
    if not ctx.rate_limiter.allow(f"ip:{_peer_ip(request)}"):
        raise ApiError("rate_limited", "too many requests from this address")
    return await handler(request)


# --------------------------------------------------------------------------- #
# 4. Signature verification
# --------------------------------------------------------------------------- #

@web.middleware
async def auth_middleware(request: web.Request, handler: Handler) -> Any:
    if not _requires_auth(request):
        return await handler(request)

    ctx = _context(request)

    # The canonical string covers the path but not the query string, so a request
    # carrying one has unsigned input. Refuse rather than silently ignore it.
    if request.query_string:
        raise ApiError("bad_request", "query strings are not permitted on signed routes")

    headers = V.parse_auth_headers(request.headers)
    max_body = ctx.config.http.max_body_bytes
    if request.content_length is not None and request.content_length > max_body:
        raise ApiError("bad_request", f"body exceeds {max_body} bytes")

    device = await ctx.store.get_device(headers.device_id)
    if device is None:
        raise ApiError("unknown_device", "this device is not paired with this server")
    if device.revoked:
        raise ApiError("device_revoked", "this device has been revoked")

    # Second bucket, keyed by device: one misbehaving phone must not consume the
    # budget that the others share by source address.
    if not ctx.rate_limiter.allow(f"dev:{device.device_id}"):
        raise ApiError("rate_limited", "too many requests from this device")

    now = int(time.time())
    V.check_timestamp(headers.timestamp, now, ctx.config.http.timestamp_skew_s)

    body = await request.read()
    if len(body) > max_body:
        raise ApiError("bad_request", f"body exceeds {max_body} bytes")

    V.verify_request_signature(
        pubkey_raw=device.pubkey,
        method=request.method,
        path=request.path,
        timestamp=headers.timestamp,
        nonce=headers.nonce,
        body=body,
        device_id=device.device_id,
        server_fp=ctx.identity.fingerprint,
        signature=headers.signature,
    )

    # The nonce is spent only now, after the signature verified. Recording it any
    # earlier would let an unauthenticated peer burn a legitimate device's nonces.
    fresh = await ctx.store.consume_nonce(
        device.device_id,
        headers.nonce,
        expires_at=now + 2 * ctx.config.http.timestamp_skew_s,
    )
    if not fresh:
        raise ApiError("replayed_nonce", "this nonce has already been used")

    request[KEY_DEVICE] = device
    await ctx.store.touch_device(device.device_id, now)
    return await handler(request)


MIDDLEWARES = (
    envelope_middleware,
    network_middleware,
    ratelimit_middleware,
    auth_middleware,
)
