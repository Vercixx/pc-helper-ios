"""Configuration validation and the rate limiter.

Bad security-relevant settings must be fatal at startup, never silently
reinterpreted.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path

import pytest

from wol_unlock import config as cfg
from wol_unlock.errors import ConfigError
from wol_unlock.ratelimit import RateLimiter


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


class TestLoading:
    def test_missing_file_uses_defaults(self, tmp_path):
        config = cfg.load(tmp_path / "absent.toml")
        assert config.name
        assert config.http.port == cfg.DEFAULT_PORT
        assert config.source_path is None

    def test_full_file(self, tmp_path):
        path = write(
            tmp_path,
            """
            name = "Studio PC"
            unlock_enabled = false
            [http]
            port = 9000
            allowed_networks = ["192.168.5.0/24"]
            timestamp_skew_s = 15
            [pairing]
            window_s = 30
            require_approval = false
            [mdns]
            enabled = false
            [[wake.targets]]
            mac = "AA-BB-CC-DD-EE-FF"
            broadcast = "192.168.5.255"
            secureon = "0b:ad:c0:ff:ee:11"
            """,
        )
        config = cfg.load(path)
        assert config.name == "Studio PC"
        assert config.http.port == 9000
        assert config.http.timestamp_skew_s == 15
        assert config.pairing.require_approval is False
        assert config.mdns_enabled is False
        assert config.unlock_enabled is False
        assert config.wake_targets[0].mac == "aa:bb:cc:dd:ee:ff"
        assert config.wake_targets[0].secureon == "0badc0ffee11"
        # unlock disabled -> not advertised as a capability
        assert "unlock" not in config.capabilities
        assert "wol" in config.capabilities

    @pytest.mark.parametrize(
        "body,match",
        [
            ('name = "' + "x" * 70 + '"', "63 bytes"),
            ("[http]\nport = 0", "http.port"),
            ("[http]\nport = 70000", "http.port"),
            ('[http]\nbind = "not-an-ip"', "http.bind"),
            ('[http]\nallowed_networks = ["nonsense"]', "invalid CIDR"),
            ("[http]\nallowed_networks = []", "non-empty"),
            ("[http]\ntimestamp_skew_s = 1", "timestamp_skew_s"),
            ("[http]\ntimestamp_skew_s = 5000", "timestamp_skew_s"),
            ("[pairing]\nwindow_s = 5", "pairing.window_s"),
            ('[pairing]\nrequire_approval = "yes"', "true or false"),
            ('[[wake.targets]]\nmac = "zz:zz:zz:zz:zz:zz"', "invalid MAC"),
            ('[[wake.targets]]\nbroadcast = "1.2.3.255"', "missing 'mac'"),
            ('[[wake.targets]]\nmac = "aa:bb:cc:dd:ee:ff"\nbroadcast = "999.1.1.1"',
             "invalid wake broadcast"),
            ('[[wake.targets]]\nmac = "aa:bb:cc:dd:ee:ff"\nbroadcast = "1.2.3.255"\n'
             'secureon = "tooshort"', "secureon"),
            ('unlock_enabled = "maybe"', "true or false"),
            ('[mdns]\nenabled = 1', "true or false"),
        ],
    )
    def test_invalid_values_are_fatal(self, tmp_path, body, match):
        with pytest.raises(ConfigError, match=match):
            cfg.load(write(tmp_path, body))

    def test_duplicate_wake_targets_rejected(self, tmp_path):
        body = (
            '[[wake.targets]]\nmac = "aa:bb:cc:dd:ee:ff"\nbroadcast = "1.2.3.255"\n'
            '[[wake.targets]]\nmac = "AA:BB:CC:DD:EE:FF"\nbroadcast = "1.2.3.255"\n'
        )
        with pytest.raises(ConfigError, match="duplicate wake target"):
            cfg.load(write(tmp_path, body))

    @pytest.mark.parametrize("body", ['name = ""', 'name = "   "', ""])
    def test_blank_name_falls_back_to_hostname(self, tmp_path, body):
        assert cfg.load(write(tmp_path, body)).name == cfg.default_display_name()

    def test_malformed_toml_is_fatal(self, tmp_path):
        with pytest.raises(ConfigError, match="cannot read"):
            cfg.load(write(tmp_path, "this is not = = toml"))

    def test_section_must_be_a_table(self, tmp_path):
        with pytest.raises(ConfigError, match=r"\[http\] must be a table"):
            cfg.load(write(tmp_path, 'http = "nope"'))


class TestAllowlist:
    def test_matching(self):
        http = cfg.HttpConfig(
            allowed_networks=(
                ipaddress.ip_network("192.168.1.0/24"),
                ipaddress.ip_network("10.0.0.0/8"),
            )
        )
        assert http.allows("192.168.1.5")
        assert http.allows("10.1.2.3")
        assert not http.allows("8.8.8.8")
        # A neighbouring RFC1918 subnet that is not in the allowlist: being
        # private is not the same as being allowed.
        assert not http.allows("192.168.2.5")
        assert not http.allows("garbage")
        assert not http.allows("")

    def test_ipv4_mapped_ipv6_peer(self):
        """A v4 peer on a dual-stack socket arrives as ::ffff:a.b.c.d and must be
        compared against the v4 rules the operator wrote."""
        http = cfg.HttpConfig(allowed_networks=(ipaddress.ip_network("192.168.1.0/24"),))
        assert http.allows("::ffff:192.168.1.5")
        assert not http.allows("::ffff:8.8.8.8")

    def test_empty_allowlist_denies_everything(self):
        assert not cfg.HttpConfig(allowed_networks=()).allows("192.168.1.5")


class TestWakeLookup:
    def test_allowlist_lookup_is_format_insensitive(self):
        config = cfg.Config(
            name="x",
            wake_targets=(cfg.WakeTarget(mac="aa:bb:cc:dd:ee:ff", broadcast="1.2.3.255"),),
        )
        assert config.wake_target_for("AA-BB-CC-DD-EE-FF") is not None
        assert config.wake_target_for("aabbccddeeff") is not None
        assert config.wake_target_for("11:22:33:44:55:66") is None


class TestDefaultGeneration:
    def test_render_is_valid_and_round_trips(self, tmp_path):
        path = write(tmp_path, cfg.render_default_toml())
        config = cfg.load(path)
        assert config.http.port == cfg.DEFAULT_PORT
        assert config.http.allowed_networks

    def test_write_refuses_to_clobber(self, tmp_path):
        path = tmp_path / "config.toml"
        cfg.write_default_config(path)
        assert path.stat().st_mode & 0o777 == 0o600
        with pytest.raises(ConfigError, match="already exists"):
            cfg.write_default_config(path)
        cfg.write_default_config(path, overwrite=True)

    def test_loopback_is_allowed_by_default(self):
        assert "127.0.0.0/8" in cfg._detect_local_networks()


class TestRateLimiter:
    def test_burst_then_refill(self):
        limiter = RateLimiter(per_minute=60, burst=3)
        now = 1000.0
        assert all(limiter.allow("k", now=now) for _ in range(3))
        assert not limiter.allow("k", now=now)
        # 60/minute == 1/second
        assert limiter.allow("k", now=now + 1.0)
        assert not limiter.allow("k", now=now + 1.0)

    def test_keys_are_independent(self):
        limiter = RateLimiter(per_minute=60, burst=1)
        assert limiter.allow("ip:a", now=1000.0)
        assert not limiter.allow("ip:a", now=1000.0)
        assert limiter.allow("ip:b", now=1000.0)

    def test_does_not_exceed_burst_after_long_idle(self):
        limiter = RateLimiter(per_minute=60, burst=3)
        assert limiter.allow("k", now=1000.0)
        for _ in range(3):
            assert limiter.allow("k", now=100000.0)
        assert not limiter.allow("k", now=100000.0)

    def test_table_is_bounded(self):
        limiter = RateLimiter(per_minute=6000, burst=1, max_keys=32)
        for index in range(500):
            limiter.allow(f"key-{index}", now=1000.0 + index)
        assert len(limiter._buckets) <= 32
