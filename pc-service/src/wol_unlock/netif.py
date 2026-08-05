"""Linux network interface introspection, without third-party dependencies.

Used for three things: generating a sensible default config, reporting link state
in ``/v1/status``, and resolving the broadcast address to send magic packets to.

Reads ``/sys/class/net`` for link attributes and uses the classic SIOC* ioctls for
addressing, so it works identically whether or not NetworkManager, systemd-networkd,
or anything else is managing the box.
"""

from __future__ import annotations

import fcntl
import socket
import struct
from dataclasses import dataclass
from pathlib import Path

SYS_NET = Path("/sys/class/net")

_SIOCGIFADDR = 0x8915
_SIOCGIFBRDADDR = 0x8919
_SIOCGIFNETMASK = 0x891B


@dataclass(frozen=True, slots=True)
class Interface:
    name: str
    mac: str | None
    ipv4: str | None
    netmask: str | None
    broadcast: str | None
    operstate: str
    carrier: bool | None

    @property
    def is_loopback(self) -> bool:
        return self.name == "lo"

    @property
    def is_up(self) -> bool:
        return self.operstate == "up"

    @property
    def link(self) -> str:
        """Compact link state for the status endpoint."""
        if self.carrier is True:
            return "up"
        if self.carrier is False:
            return "down"
        return self.operstate


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except (OSError, UnicodeDecodeError):
        return None


def _ioctl_addr(sock: socket.socket, name: str, request: int) -> str | None:
    """Fetch an IPv4 address family attribute for an interface, or None."""
    try:
        packed = fcntl.ioctl(
            sock.fileno(), request, struct.pack("256s", name.encode("ascii")[:15])
        )
    except OSError:
        return None
    return socket.inet_ntoa(packed[20:24])


def list_interfaces(*, include_loopback: bool = False) -> list[Interface]:
    """Every interface the kernel knows about, sorted by name."""
    try:
        names = sorted(p.name for p in SYS_NET.iterdir())
    except OSError:
        return []

    result: list[Interface] = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for name in names:
            if name == "lo" and not include_loopback:
                continue
            base = SYS_NET / name
            mac = _read(base / "address")
            if mac in ("00:00:00:00:00:00", ""):
                mac = None
            carrier_raw = _read(base / "carrier")
            # 'carrier' reads EINVAL (-> None here) while the interface is down;
            # that is a real third state, not a failure, so it stays None.
            carrier = None if carrier_raw is None else carrier_raw == "1"
            result.append(
                Interface(
                    name=name,
                    mac=mac,
                    ipv4=_ioctl_addr(sock, name, _SIOCGIFADDR),
                    netmask=_ioctl_addr(sock, name, _SIOCGIFNETMASK),
                    broadcast=_ioctl_addr(sock, name, _SIOCGIFBRDADDR),
                    operstate=_read(base / "operstate") or "unknown",
                    carrier=carrier,
                )
            )
    return result


def get_interface(name: str) -> Interface | None:
    for iface in list_interfaces(include_loopback=True):
        if iface.name == name:
            return iface
    return None


def wakeable_interfaces() -> list[Interface]:
    """Physical interfaces worth listing as Wake-on-LAN targets.

    Filters out loopback, interfaces without a MAC, and the usual virtual clutter
    (bridges, tunnels, VPN and container interfaces) which can never be woken.
    """
    virtual_prefixes = (
        "lo", "docker", "veth", "br-", "virbr", "tun", "tap", "wg",
        "zt", "tailscale", "vmnet", "bond", "dummy", "ifb", "sit",
    )
    out = []
    for iface in list_interfaces():
        if iface.mac is None:
            continue
        if iface.name.startswith(virtual_prefixes):
            continue
        # A real NIC has a device symlink in sysfs; virtual ones generally do not.
        if not (SYS_NET / iface.name / "device").exists():
            continue
        out.append(iface)
    return out


def primary_broadcast() -> str | None:
    """Broadcast address of the interface carrying the default route.

    Falls back to the first up interface with a broadcast address.
    """
    default_iface = _default_route_interface()
    interfaces = list_interfaces()
    if default_iface:
        for iface in interfaces:
            if iface.name == default_iface and iface.broadcast:
                return iface.broadcast
    for iface in interfaces:
        if iface.is_up and iface.broadcast and iface.broadcast != "0.0.0.0":
            return iface.broadcast
    return None


def _default_route_interface() -> str | None:
    """Interface name from /proc/net/route (destination 0.0.0.0)."""
    try:
        lines = Path("/proc/net/route").read_text().splitlines()
    except OSError:
        return None
    for line in lines[1:]:
        fields = line.split()
        if len(fields) >= 3 and fields[1] == "00000000":
            return fields[0]
    return None
