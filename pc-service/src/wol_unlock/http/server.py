"""aiohttp application assembly and lifecycle."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from ..context import ServiceContext
from . import handlers
from .middleware import APP_CONTEXT, MIDDLEWARES, PUBLIC_PATHS, REQUIRES_AUTH

log = logging.getLogger("wol_unlock.http")

ROUTES: tuple[tuple[str, str, Any], ...] = (
    ("GET", "/v1/server-info", handlers.server_info),
    ("POST", "/v1/pair", handlers.pair),
    ("GET", "/v1/status", handlers.status),
    ("POST", "/v1/wake", handlers.wake),
    ("POST", "/v1/unlock", handlers.unlock),
)


def _assert_auth_annotations_agree() -> None:
    """Fail at startup if a handler's @signed annotation disagrees with
    ``PUBLIC_PATHS``.

    The middleware decides authentication from ``PUBLIC_PATHS`` alone, so a
    missing decorator cannot open a hole. This check exists so the two
    descriptions of intent cannot silently drift apart and mislead a reader.
    """
    for _, path, handler in ROUTES:
        annotated = bool(getattr(handler, REQUIRES_AUTH, False))
        expected = path not in PUBLIC_PATHS
        if annotated != expected:
            raise RuntimeError(
                f"route {path} is {'@signed' if annotated else 'unannotated'} but "
                f"PUBLIC_PATHS says it {'does not need' if not expected else 'needs'} "
                f"authentication; fix one of them"
            )


def build_app(context: ServiceContext) -> web.Application:
    _assert_auth_annotations_agree()
    app = web.Application(
        middlewares=list(MIDDLEWARES),
        # aiohttp enforces this while reading; anything larger is rejected before
        # the body reaches us, and the envelope middleware turns it into a signed
        # 413 rather than aiohttp's bare HTML error page.
        client_max_size=context.config.http.max_body_bytes,
        logger=log,
    )
    app[APP_CONTEXT] = context
    for method, path, handler in ROUTES:
        app.router.add_route(method, path, handler)
    return app


class HttpServer:
    """Owns the runner and site so shutdown is orderly."""

    def __init__(self, context: ServiceContext) -> None:
        self._context = context
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        cfg = self._context.config.http
        app = build_app(self._context)
        # The audit table is the access record; aiohttp's own access log would
        # duplicate it in a less useful form.
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, cfg.bind, cfg.port, reuse_address=True)
        await site.start()
        self._runner = runner
        log.info(
            "HTTP API listening on %s:%d (allowed: %s)",
            cfg.bind,
            cfg.port,
            ", ".join(str(net) for net in cfg.allowed_networks),
        )

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None


async def run_http(context: ServiceContext) -> HttpServer:
    server = HttpServer(context)
    await server.start()
    return server
