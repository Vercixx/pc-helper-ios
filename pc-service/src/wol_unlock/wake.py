"""Wake-on-LAN magic packets.

Scope note: this module can only wake *other* hosts. The machine running the
service is, by definition, awake -- and when it is asleep nothing here is running
to receive a request. Waking this PC is the phone's job, which is why the iOS
native module opens its own UDP socket rather than calling ``POST /v1/wake``.
Both implementations build the identical packet described in PROTOCOL.md 7.
"""

from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .config import WakeTarget, normalize_mac
from .errors import ApiError

MAGIC_PREFIX = b"\xff" * 6
MAC_REPEAT = 16
PACKET_LEN = 102
PACKET_LEN_SECUREON = 108


def build_magic_packet(mac: str, secureon: str | None = None) -> bytes:
    """``FF*6`` + MAC*16, optionally + a 6-byte SecureOn password.

    102 bytes, or 108 with SecureOn. See the golden vectors in PROTOCOL.md 11.6.
    """
    mac_bytes = bytes.fromhex(normalize_mac(mac).replace(":", ""))
    packet = MAGIC_PREFIX + mac_bytes * MAC_REPEAT
    if secureon:
        cleaned = secureon.replace(":", "").replace("-", "").lower()
        if len(cleaned) != 12:
            raise ValueError("secureon password must be 6 bytes")
        packet += bytes.fromhex(cleaned)
    assert len(packet) in (PACKET_LEN, PACKET_LEN_SECUREON)
    return packet


def _send_sync(packet: bytes, broadcast: str, port: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # Bind to an ephemeral port on all interfaces; the route to the
        # subnet-directed broadcast address selects the egress interface, which is
        # what we want on a multi-homed host.
        sock.settimeout(2.0)
        return sock.sendto(packet, (broadcast, port))


@dataclass(frozen=True, slots=True)
class WakeSendResult:
    mac: str
    via: str
    bytes_sent: int

    def to_dict(self) -> dict[str, Any]:
        return {"mac": self.mac, "via": self.via, "bytes": self.bytes_sent}


async def send_to_target(target: WakeTarget) -> WakeSendResult:
    """Send one magic packet, raising ``wake_failed`` on a socket error."""
    packet = build_magic_packet(target.mac, target.secureon)
    try:
        sent = await asyncio.to_thread(_send_sync, packet, target.broadcast, target.port)
    except OSError as exc:
        raise ApiError(
            "wake_failed",
            f"cannot send magic packet to {target.broadcast}:{target.port}: {exc}",
        ) from exc
    return WakeSendResult(
        mac=target.mac, via=f"{target.broadcast}:{target.port}", bytes_sent=sent
    )


async def send_to_targets(targets: Sequence[WakeTarget]) -> list[WakeSendResult]:
    """Fan out to every target.

    Partial success is success: a machine with both a wired and a wireless NIC
    only needs one packet to land, and refusing the whole request because one
    interface is unroutable would be unhelpful. Every target failing is an error.
    """
    if not targets:
        raise ApiError("wake_failed", "no wake targets are configured")

    results: list[WakeSendResult] = []
    errors: list[str] = []
    for target in targets:
        try:
            results.append(await send_to_target(target))
        except ApiError as exc:
            errors.append(f"{target.mac}: {exc.message}")

    if not results:
        raise ApiError("wake_failed", "; ".join(errors))
    return results


def describe_targets(targets: Iterable[WakeTarget]) -> list[dict[str, Any]]:
    """Target list with live link state, for ``GET /v1/status``."""
    from . import netif

    interfaces = {iface.name: iface for iface in netif.list_interfaces(include_loopback=True)}
    out: list[dict[str, Any]] = []
    for target in targets:
        iface = interfaces.get(target.iface) if target.iface else None
        out.append(
            {
                "mac": target.mac,
                "iface": target.iface,
                "broadcast": target.broadcast,
                "port": target.port,
                "link": iface.link if iface else "unknown",
            }
        )
    return out
