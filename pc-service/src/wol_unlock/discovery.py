"""mDNS / DNS-SD advertisement and browsing for ``_wol-unlock._tcp``.

Uses python-zeroconf's own protocol stack rather than avahi, so the service has
no dependency on a system daemon that may not be installed or running. Port 5353
is joined with SO_REUSEPORT, so this coexists with avahi, systemd-resolved, and
the several desktop applications that already listen there.

Discovery is *untrusted hinting*. A record supplies candidate addresses and lets
the app recognise an already-paired PC by fingerprint; it never establishes
identity. Spoofing a record achieves nothing, because every response the client
subsequently receives is signed by a key it pinned at pairing time.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
from typing import Any

from zeroconf import IPVersion, ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

from . import netif
from .context import ServiceContext

log = logging.getLogger("wol_unlock.discovery")

SERVICE_TYPE = "_wol-unlock._tcp.local."


def local_hostname() -> str:
    return socket.gethostname().split(".")[0] or "linux-pc"


def _local_addresses() -> list[bytes]:
    """Packed IPv4 addresses to publish, one per up interface."""
    packed: list[bytes] = []
    for iface in netif.list_interfaces():
        if not iface.ipv4 or not iface.is_up or iface.ipv4.startswith("127."):
            continue
        try:
            packed.append(socket.inet_aton(iface.ipv4))
        except OSError:
            continue
    return packed


def build_txt(context: ServiceContext) -> dict[bytes, bytes]:
    """TXT record contents (PROTOCOL.md 8).

    Everything here is also served by the unauthenticated ``/v1/server-info``
    endpoint, so publishing it discloses nothing new.
    """
    return {
        b"v": b"1",
        b"api": b"1",
        b"name": context.config.name.encode("utf-8")[:255],
        b"caps": ",".join(context.config.capabilities).encode("ascii"),
        b"fp": context.identity.fingerprint.encode("ascii"),
        b"pair": b"1" if context.pairing.is_open else b"0",
    }


class Advertiser:
    """Publishes this service and keeps the ``pair`` flag current."""

    def __init__(self, context: ServiceContext) -> None:
        self._context = context
        self._zc: AsyncZeroconf | None = None
        self._info: AsyncServiceInfo | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        hostname = local_hostname()
        addresses = _local_addresses()
        if not addresses:
            log.warning("no usable IPv4 address found; skipping mDNS advertisement")
            return

        self._info = AsyncServiceInfo(
            SERVICE_TYPE,
            f"{hostname}.{SERVICE_TYPE}",
            addresses=addresses,
            port=self._context.config.http.port,
            properties=build_txt(self._context),
            server=f"{hostname}.local.",
        )
        self._zc = AsyncZeroconf(ip_version=IPVersion.V4Only)
        await self._zc.async_register_service(self._info, allow_name_change=True)
        self._context.pairing.add_listener(self._on_pairing_event)
        log.info(
            "advertising %s on port %d (fp %s)",
            self._info.name,
            self._context.config.http.port,
            self._context.identity.short_fingerprint,
        )

    def _on_pairing_event(self, name: str, _data: dict[str, Any]) -> None:
        """Flip the ``pair`` TXT flag as the window opens and closes.

        Emitted synchronously from inside the pairing lock, so the actual mDNS
        update is deferred to a task rather than awaited here.
        """
        if name not in ("pair.opened", "pair.closed"):
            return
        with contextlib.suppress(RuntimeError):
            asyncio.get_running_loop().create_task(self.refresh())

    async def refresh(self) -> None:
        async with self._lock:
            if self._zc is None or self._info is None:
                return
            self._info.properties = build_txt(self._context)
            with contextlib.suppress(Exception):
                await self._zc.async_update_service(self._info)

    async def stop(self) -> None:
        self._context.pairing.remove_listener(self._on_pairing_event)
        async with self._lock:
            if self._zc is not None:
                with contextlib.suppress(Exception):
                    if self._info is not None:
                        await self._zc.async_unregister_service(self._info)
                    await self._zc.async_close()
            self._zc = None
            self._info = None


async def browse(timeout: float = 3.0) -> list[dict[str, Any]]:
    """Browse the LAN for advertised services. Used by ``wol-unlockctl discover``
    as a self-test that the advertisement is actually visible on the wire."""
    found: dict[str, dict[str, Any]] = {}
    azc = AsyncZeroconf(ip_version=IPVersion.V4Only)
    pending: list[asyncio.Task[None]] = []

    async def resolve(zeroconf: Any, service_type: str, name: str) -> None:
        info = AsyncServiceInfo(service_type, name)
        if not await info.async_request(zeroconf, 2500):
            return
        props: dict[str, str] = {}
        for key, value in (info.properties or {}).items():
            try:
                props[key.decode("ascii")] = (value or b"").decode("utf-8", "replace")
            except (AttributeError, UnicodeDecodeError):
                continue
        found[name] = {
            "name": props.get("name") or name.split(".")[0],
            "instance": name,
            "host": (info.server or "").rstrip("."),
            "port": info.port,
            "addresses": info.parsed_addresses(),
            "fp": props.get("fp", ""),
            "caps": props.get("caps", ""),
            "pair": props.get("pair", "0"),
            "api": props.get("api", ""),
        }

    def on_change(zeroconf: Any, service_type: str, name: str,
                  state_change: ServiceStateChange) -> None:
        if state_change is ServiceStateChange.Removed:
            found.pop(name, None)
            return
        pending.append(asyncio.ensure_future(resolve(zeroconf, service_type, name)))

    browser = AsyncServiceBrowser(azc.zeroconf, SERVICE_TYPE, handlers=[on_change])
    try:
        await asyncio.sleep(timeout)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    finally:
        await browser.async_cancel()
        await azc.async_close()

    return sorted(found.values(), key=lambda item: item["name"].lower())
