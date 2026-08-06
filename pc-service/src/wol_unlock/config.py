"""Configuration loading, validation, and first-run generation.

Every security-relevant knob is validated at startup and the process refuses to
run on bad input (:class:`~wol_unlock.errors.ConfigError`). A service that starts
with, say, an unparseable CIDR in ``allowed_networks`` and quietly falls back to
"allow everything" is worse than one that does not start.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .errors import ConfigError
from . import netif

APP_NAME = "wol-unlock"

DEFAULT_PORT = 8765
DEFAULT_WOL_PORT = 9


# --------------------------------------------------------------------------- #
# XDG paths
# --------------------------------------------------------------------------- #

def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / APP_NAME


def config_path() -> Path:
    return config_dir() / "config.toml"


def state_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / APP_NAME


def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base:
        return Path(base)
    # No runtime dir (cron, ssh without pam_systemd): fall back to a private
    # directory under the state dir rather than /tmp, which is world-writable.
    fallback = state_dir() / "run"
    fallback.mkdir(parents=True, exist_ok=True, mode=0o700)
    return fallback


def control_socket_path() -> Path:
    return runtime_dir() / f"{APP_NAME}.sock"


# --------------------------------------------------------------------------- #
# Normalisation helpers
# --------------------------------------------------------------------------- #

def normalize_mac(value: str) -> str:
    """Accept ``aa:bb:..``, ``aa-bb-..`` or bare hex; emit lowercase colon form."""
    cleaned = str(value).strip().lower().replace("-", "").replace(":", "").replace(".", "")
    if len(cleaned) != 12 or not all(c in "0123456789abcdef" for c in cleaned):
        raise ConfigError(f"invalid MAC address: {value!r}")
    return ":".join(cleaned[i : i + 2] for i in range(0, 12, 2))


def _validate_ipv4(value: str, what: str) -> str:
    try:
        return str(ipaddress.IPv4Address(str(value).strip()))
    except ValueError as exc:
        raise ConfigError(f"invalid {what}: {value!r}") from exc


def _validate_port(value: Any, what: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not (1 <= value <= 65535):
        raise ConfigError(f"invalid {what}: {value!r} (expected 1-65535)")
    return value


def _validate_int_range(value: Any, what: str, low: int, high: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not (low <= value <= high):
        raise ConfigError(f"invalid {what}: {value!r} (expected {low}-{high})")
    return value


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #

@dataclass(frozen=True, slots=True)
class WakeTarget:
    mac: str
    broadcast: str
    port: int = DEFAULT_WOL_PORT
    iface: str | None = None
    secureon: str | None = None  # 6-byte SecureOn password, lowercase hex

    @classmethod
    def from_toml(cls, raw: Any, default_broadcast: str | None) -> "WakeTarget":
        if not isinstance(raw, dict):
            raise ConfigError("each [[wake.targets]] entry must be a table")
        if "mac" not in raw:
            raise ConfigError("[[wake.targets]] entry is missing 'mac'")
        broadcast = raw.get("broadcast") or default_broadcast
        if not broadcast:
            raise ConfigError(
                f"wake target {raw['mac']!r} has no 'broadcast' and none could be detected"
            )
        secureon = raw.get("secureon") or None
        if secureon is not None:
            cleaned = str(secureon).replace(":", "").replace("-", "").lower()
            if len(cleaned) != 12 or not all(c in "0123456789abcdef" for c in cleaned):
                raise ConfigError(
                    f"invalid secureon for {raw['mac']!r}: expected 6 hex bytes"
                )
            secureon = cleaned
        iface = raw.get("iface")
        return cls(
            mac=normalize_mac(raw["mac"]),
            broadcast=_validate_ipv4(broadcast, "wake broadcast address"),
            port=_validate_port(raw.get("port", DEFAULT_WOL_PORT), "wake port"),
            iface=str(iface) if iface else None,
            secureon=secureon,
        )


@dataclass(frozen=True, slots=True)
class HttpConfig:
    port: int = DEFAULT_PORT
    bind: str = "0.0.0.0"
    allowed_networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = ()
    max_body_bytes: int = 8192
    timestamp_skew_s: int = 30
    # Generous enough for the app's post-wake status polling (one call every 2s
    # for ~30s) plus normal interaction, tight enough to make online guessing of
    # a pairing code pointless.
    rate_limit_per_minute: int = 120
    rate_limit_burst: int = 30

    def allows(self, addr: str) -> bool:
        """Whether a peer address falls inside the configured LAN allowlist."""
        if not self.allowed_networks:
            return False
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        # An IPv4 peer arriving on a dual-stack socket shows up as ::ffff:a.b.c.d;
        # compare it against the IPv4 rules the operator actually wrote.
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        return any(ip in net for net in self.allowed_networks)

    @classmethod
    def from_toml(cls, raw: dict[str, Any]) -> "HttpConfig":
        networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        entries = raw.get("allowed_networks")
        if entries is None:
            entries = _detect_local_networks()
        if not isinstance(entries, list) or not entries:
            raise ConfigError("http.allowed_networks must be a non-empty list of CIDRs")
        for entry in entries:
            try:
                networks.append(ipaddress.ip_network(str(entry), strict=False))
            except ValueError as exc:
                raise ConfigError(f"invalid CIDR in http.allowed_networks: {entry!r}") from exc

        bind = str(raw.get("bind", "0.0.0.0"))
        try:
            ipaddress.ip_address(bind)
        except ValueError as exc:
            raise ConfigError(f"invalid http.bind address: {bind!r}") from exc

        return cls(
            port=_validate_port(raw.get("port", DEFAULT_PORT), "http.port"),
            bind=bind,
            allowed_networks=tuple(networks),
            max_body_bytes=_validate_int_range(
                raw.get("max_body_bytes", 8192), "http.max_body_bytes", 256, 1_048_576
            ),
            timestamp_skew_s=_validate_int_range(
                raw.get("timestamp_skew_s", 30), "http.timestamp_skew_s", 5, 300
            ),
            rate_limit_per_minute=_validate_int_range(
                raw.get("rate_limit_per_minute", 120), "http.rate_limit_per_minute", 1, 10_000
            ),
            rate_limit_burst=_validate_int_range(
                raw.get("rate_limit_burst", 30), "http.rate_limit_burst", 1, 1_000
            ),
        )


@dataclass(frozen=True, slots=True)
class PairingConfig:
    window_s: int = 120
    require_approval: bool = True
    max_attempts: int = 3
    approval_timeout_s: int = 60

    @classmethod
    def from_toml(cls, raw: dict[str, Any]) -> "PairingConfig":
        require_approval = raw.get("require_approval", True)
        if not isinstance(require_approval, bool):
            raise ConfigError("pairing.require_approval must be true or false")
        return cls(
            window_s=_validate_int_range(raw.get("window_s", 120), "pairing.window_s", 15, 600),
            require_approval=require_approval,
            max_attempts=_validate_int_range(
                raw.get("max_attempts", 3), "pairing.max_attempts", 1, 10
            ),
            approval_timeout_s=_validate_int_range(
                raw.get("approval_timeout_s", 60), "pairing.approval_timeout_s", 10, 300
            ),
        )


@dataclass(frozen=True, slots=True)
class Config:
    name: str
    http: HttpConfig = field(default_factory=HttpConfig)
    pairing: PairingConfig = field(default_factory=PairingConfig)
    wake_targets: tuple[WakeTarget, ...] = ()
    mdns_enabled: bool = True
    unlock_enabled: bool = True
    lock_enabled: bool = True
    state_dir: Path = field(default_factory=state_dir)
    source_path: Path | None = None

    @property
    def capabilities(self) -> tuple[str, ...]:
        caps = ["status"]
        if self.wake_targets:
            caps.append("wol")
        if self.unlock_enabled:
            caps.append("unlock")
        if self.lock_enabled:
            caps.append("lock")
        return tuple(sorted(caps))

    def wake_target_for(self, mac: str) -> WakeTarget | None:
        """Look up an allowlisted target. Relay requests for anything else are
        refused, so this endpoint cannot be used as an open broadcast relay."""
        wanted = normalize_mac(mac)
        for target in self.wake_targets:
            if target.mac == wanted:
                return target
        return None


# --------------------------------------------------------------------------- #
# Loading and generation
# --------------------------------------------------------------------------- #

def _detect_local_networks() -> list[str]:
    """CIDRs for every interface with an IPv4 address, as an allowlist default.

    Loopback is included so that ``curl localhost:8765`` and the reference client
    work out of the box. Reaching the service over loopback already requires an
    account on this machine, so it grants nothing that local access does not.
    """
    nets: list[str] = ["127.0.0.0/8"]
    for iface in netif.list_interfaces():
        if not iface.ipv4 or not iface.netmask:
            continue
        try:
            net = ipaddress.ip_network(f"{iface.ipv4}/{iface.netmask}", strict=False)
        except ValueError:
            continue
        if net.is_loopback:
            continue
        text = str(net)
        if text not in nets:
            nets.append(text)
    return nets or ["192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12"]


def default_display_name() -> str:
    host = socket.gethostname().split(".")[0] or "Linux PC"
    return host


def load(path: Path | None = None) -> Config:
    """Read and validate the config file.

    A missing file is not an error: the built-in defaults plus autodetected
    interfaces are a working configuration, which keeps first run friction-free.
    """
    path = path or config_path()
    raw: dict[str, Any] = {}
    if path.exists():
        try:
            with path.open("rb") as handle:
                raw = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"cannot read {path}: {exc}") from exc

    # An absent, empty or whitespace-only name all mean the same thing: fall back
    # to the hostname. Treating "" and " " differently would be a surprise, and
    # the display name is not security-relevant enough to refuse startup over.
    name = str(raw.get("name") or "").strip() or default_display_name()
    # mDNS instance labels are capped at 63 bytes.
    if len(name.encode("utf-8")) > 63:
        raise ConfigError("name must be at most 63 bytes when UTF-8 encoded")

    for section in ("http", "pairing", "wake", "mdns"):
        if section in raw and not isinstance(raw[section], dict):
            raise ConfigError(f"[{section}] must be a table")

    wake_raw = raw.get("wake", {})
    targets_raw = wake_raw.get("targets")
    default_broadcast = netif.primary_broadcast()
    if targets_raw is None:
        targets = tuple(_default_wake_targets(default_broadcast))
    else:
        if not isinstance(targets_raw, list):
            raise ConfigError("wake.targets must be an array of tables")
        targets = tuple(WakeTarget.from_toml(item, default_broadcast) for item in targets_raw)

    seen: set[str] = set()
    for target in targets:
        if target.mac in seen:
            raise ConfigError(f"duplicate wake target MAC {target.mac}")
        seen.add(target.mac)

    mdns_raw = raw.get("mdns", {})
    mdns_enabled = mdns_raw.get("enabled", True)
    if not isinstance(mdns_enabled, bool):
        raise ConfigError("mdns.enabled must be true or false")

    unlock_enabled = raw.get("unlock_enabled", True)
    if not isinstance(unlock_enabled, bool):
        raise ConfigError("unlock_enabled must be true or false")

    lock_enabled = raw.get("lock_enabled", True)
    if not isinstance(lock_enabled, bool):
        raise ConfigError("lock_enabled must be true or false")

    return Config(
        name=name,
        http=HttpConfig.from_toml(raw.get("http", {})),
        pairing=PairingConfig.from_toml(raw.get("pairing", {})),
        wake_targets=targets,
        mdns_enabled=mdns_enabled,
        unlock_enabled=unlock_enabled,
        lock_enabled=lock_enabled,
        state_dir=state_dir(),
        source_path=path if path.exists() else None,
    )


def _default_wake_targets(default_broadcast: str | None) -> Iterable[WakeTarget]:
    if not default_broadcast:
        return []
    return [
        WakeTarget(mac=iface.mac, broadcast=default_broadcast, iface=iface.name)
        for iface in netif.wakeable_interfaces()
        if iface.mac
    ]


def render_default_toml() -> str:
    """A commented config reflecting this machine's actual interfaces."""
    broadcast = netif.primary_broadcast() or "192.168.1.255"
    lines = [
        "# wol-unlock configuration",
        "# Regenerate with:  wol-unlock --write-default-config",
        "",
        f'name = "{default_display_name()}"',
        "",
        "# Set false to refuse every unlock request regardless of pairing.",
        "unlock_enabled = true",
        "",
        "# Locking is the safe half of the pair -- the worst it can do is cost",
        "# you a password prompt -- so it has its own switch, and turning unlock",
        "# off does not take it away.",
        "lock_enabled = true",
        "",
        "[http]",
        f"port = {DEFAULT_PORT}",
        'bind = "0.0.0.0"',
        "# Requests from outside these ranges are dropped before any crypto runs.",
        "allowed_networks = ["
        + ", ".join(f'"{net}"' for net in _detect_local_networks())
        + "]",
        "max_body_bytes = 8192",
        "# Freshness window for signed requests, in seconds.",
        "timestamp_skew_s = 30",
        "rate_limit_per_minute = 120",
        "rate_limit_burst = 30",
        "",
        "[pairing]",
        "# How long a pairing code stays valid once opened from the terminal.",
        "window_s = 120",
        "# Require an explicit y/N at the terminal for each enrolling device.",
        "require_approval = true",
        "max_attempts = 3",
        "approval_timeout_s = 60",
        "",
        "[mdns]",
        "enabled = true",
        "",
    ]
    targets = list(netif.wakeable_interfaces())
    if targets:
        lines.append("# Wake-on-LAN targets. Only MACs listed here may be relayed via POST /v1/wake.")
    for iface in targets:
        lines += [
            "[[wake.targets]]",
            f'mac = "{iface.mac}"        # {iface.name} ({iface.link})',
            f'iface = "{iface.name}"',
            f'broadcast = "{broadcast}"',
            f"port = {DEFAULT_WOL_PORT}",
            '# secureon = "0b:ad:c0:ff:ee:11"   # only if your NIC supports it',
            "",
        ]
    return "\n".join(lines)


def write_default_config(path: Path | None = None, *, overwrite: bool = False) -> Path:
    path = path or config_path()
    if path.exists() and not overwrite:
        raise ConfigError(f"{path} already exists (use --force to overwrite)")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(render_default_toml(), encoding="utf-8")
    path.chmod(0o600)
    return path
