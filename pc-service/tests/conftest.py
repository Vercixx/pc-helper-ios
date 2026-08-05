"""Shared fixtures.

The Ed25519 seeds here are the ones published in PROTOCOL.md section 11 so that
tests and specification cannot drift apart.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from wol_unlock import config as config_mod
from wol_unlock import identity as identity_mod
from wol_unlock.context import ServiceContext
from wol_unlock.pairing import PairingManager
from wol_unlock.ratelimit import RateLimiter
from wol_unlock.store import Store

DEVICE_SEED = bytes(range(0, 32))
SERVER_SEED = bytes(range(32, 64))

# Captured verbatim from `loginctl --json=short list-sessions` on a KDE/Wayland
# Arch box. Session 2 is the systemd 'manager' session that must never be chosen.
LOGINCTL_SESSIONS_JSON = (
    '[{"session":"1","uid":1000,"user":"alice","seat":"seat0","leader":830,'
    '"class":"user","tty":"tty1","idle":false,"since":null},'
    '{"session":"2","uid":1000,"user":"alice","seat":null,"leader":839,'
    '"class":"manager","tty":null,"idle":false,"since":null}]'
)

SHOW_SESSION_GRAPHICAL = (
    "User=1000\nName=alice\nSeat=seat0\nDesktop=KDE\n"
    "Type=wayland\nClass=user\nActive=yes\nLockedHint=no\n"
)


@pytest.fixture
def device_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(DEVICE_SEED)


@pytest.fixture
def server_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(SERVER_SEED)


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "state"
    directory.mkdir(mode=0o700)
    return directory


@pytest.fixture
def test_config(state_dir: Path) -> config_mod.Config:
    return config_mod.Config(
        name="Test PC",
        http=config_mod.HttpConfig(
            port=0,
            bind="127.0.0.1",
            allowed_networks=(ipaddress.ip_network("127.0.0.0/8"),),
            timestamp_skew_s=30,
            rate_limit_per_minute=6000,
            rate_limit_burst=500,
        ),
        pairing=config_mod.PairingConfig(window_s=60, require_approval=False),
        wake_targets=(
            config_mod.WakeTarget(
                mac="00:00:5e:00:53:01", broadcast="127.0.0.255", port=9, iface="enp11s0"
            ),
        ),
        mdns_enabled=False,
        state_dir=state_dir,
    )


@pytest.fixture
async def store(state_dir: Path):
    instance = await Store.open(state_dir / "state.db")
    yield instance
    await instance.close()


@pytest.fixture
def identity(state_dir: Path, server_key: Ed25519PrivateKey) -> identity_mod.ServerIdentity:
    """A deterministic server identity, so fingerprints in assertions are stable."""
    return identity_mod.ServerIdentity(private_key=server_key, path=state_dir / "server_key.pem")


@pytest.fixture
async def context(test_config, identity, store) -> ServiceContext:
    return ServiceContext(
        config=test_config,
        identity=identity,
        store=store,
        pairing=PairingManager(test_config, identity, store),
        rate_limiter=RateLimiter(
            test_config.http.rate_limit_per_minute, test_config.http.rate_limit_burst
        ),
    )
