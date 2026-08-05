"""Service assembly and lifecycle."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from .config import Config, control_socket_path
from .context import ServiceContext
from .control.server import ControlServer
from .discovery import Advertiser
from .http.server import HttpServer
from .identity import load_or_create
from .pairing import PairingManager
from .ratelimit import RateLimiter
from .store import Store

log = logging.getLogger("wol_unlock.service")

#: How often expired nonces are swept. Rows are only kept for
#: ``2 * timestamp_skew_s``, so this is frequent enough to keep the table tiny.
SWEEP_INTERVAL_S = 30

#: Audit rows retained. Bounded so a peer hammering the API cannot fill the disk.
AUDIT_KEEP = 5000


class Service:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._context: ServiceContext | None = None
        self._store: Store | None = None
        self._http: HttpServer | None = None
        self._control: ControlServer | None = None
        self._advertiser: Advertiser | None = None
        self._sweeper: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    @property
    def context(self) -> ServiceContext:
        if self._context is None:
            raise RuntimeError("service is not started")
        return self._context

    async def start(self) -> None:
        cfg = self._config

        identity = load_or_create(cfg.state_dir)
        log.info("server identity %s (%s)", identity.short_fingerprint, identity.path)

        store = await Store.open(cfg.state_dir / "state.db")
        self._store = store

        pairing = PairingManager(cfg, identity, store)
        self._context = ServiceContext(
            config=cfg,
            identity=identity,
            store=store,
            pairing=pairing,
            rate_limiter=RateLimiter(cfg.http.rate_limit_per_minute, cfg.http.rate_limit_burst),
        )

        # Control socket first: if a second instance is already running it owns
        # the socket, and we want to fail before binding the TCP port.
        self._control = ControlServer(self._context, control_socket_path())
        await self._control.start()

        self._http = HttpServer(self._context)
        await self._http.start()

        if cfg.mdns_enabled:
            self._advertiser = Advertiser(self._context)
            self._context.discovery = self._advertiser
            try:
                await self._advertiser.start()
            except Exception:  # noqa: BLE001
                # Discovery is a convenience; pairing by QR carries the address
                # anyway. Losing mDNS must not take the service down.
                log.warning("mDNS advertisement failed; continuing", exc_info=True)
                self._advertiser = None

        self._sweeper = asyncio.create_task(self._sweep_loop())

        devices = await store.list_devices(include_revoked=False)
        log.info(
            "ready: %d trusted device(s), unlock %s, %d wake target(s)",
            len(devices),
            "enabled" if cfg.unlock_enabled else "disabled",
            len(cfg.wake_targets),
        )
        if not devices:
            log.info("no devices paired yet -- run 'wol-unlockctl pair' to enroll one")

    async def _sweep_loop(self) -> None:
        """Drop expired nonces and cap the audit table."""
        while True:
            try:
                await asyncio.sleep(SWEEP_INTERVAL_S)
                if self._store is None:
                    return
                removed = await self._store.sweep_nonces(int(time.time()))
                if removed:
                    log.debug("swept %d expired nonce(s)", removed)
                await self._store.prune_audit(AUDIT_KEEP)
            except asyncio.CancelledError:
                return
            except Exception:  # noqa: BLE001
                log.warning("sweep failed", exc_info=True)

    async def stop(self) -> None:
        log.info("shutting down")
        if self._sweeper is not None:
            self._sweeper.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._sweeper
            self._sweeper = None

        if self._context is not None:
            await self._context.pairing.shutdown()
        for component in (self._advertiser, self._http, self._control):
            if component is not None:
                with contextlib.suppress(Exception):
                    await component.stop()
        self._advertiser = self._http = self._control = None

        if self._store is not None:
            await self._store.close()
            self._store = None
        self._stopped.set()

    async def wait_closed(self) -> None:
        await self._stopped.wait()

    def request_stop(self) -> None:
        self._stopped.set()
