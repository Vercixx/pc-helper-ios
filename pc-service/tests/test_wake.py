"""Magic packet construction (PROTOCOL.md 7 and 11.6)."""

from __future__ import annotations

import pytest

from wol_unlock.config import WakeTarget, normalize_mac
from wol_unlock.errors import ApiError, ConfigError
from wol_unlock.wake import build_magic_packet, send_to_targets

ETH_MAC = "00:00:5e:00:53:01"
WIFI_MAC = "00:00:5e:00:53:02"

ETH_PACKET_HEX = "ffffffffffff" + "00005e005301" * 16
WIFI_PACKET_HEX = "ffffffffffff" + "00005e005302" * 16


def test_golden_vector_ethernet():
    packet = build_magic_packet(ETH_MAC)
    assert len(packet) == 102
    assert packet.hex() == ETH_PACKET_HEX


def test_golden_vector_wifi():
    packet = build_magic_packet(WIFI_MAC)
    assert len(packet) == 102
    assert packet.hex() == WIFI_PACKET_HEX


def test_structure():
    packet = build_magic_packet(ETH_MAC)
    assert packet[:6] == b"\xff" * 6
    mac = bytes.fromhex("00005e005301")
    for index in range(16):
        offset = 6 + index * 6
        assert packet[offset : offset + 6] == mac


def test_secureon_appends_six_bytes():
    packet = build_magic_packet(ETH_MAC, "0b:ad:c0:ff:ee:11")
    assert len(packet) == 108
    assert packet.hex() == ETH_PACKET_HEX + "0badc0ffee11"


@pytest.mark.parametrize("secureon", ["0badc0ffee", "0badc0ffee1122", "zz:ad:c0:ff:ee:11"])
def test_bad_secureon_rejected(secureon):
    with pytest.raises(ValueError):
        build_magic_packet(ETH_MAC, secureon)


@pytest.mark.parametrize(
    "written", ["00:00:5e:00:53:01", "00-00-5E-00-53-01", "00005e005301", "00:00:5E:00:53:01"]
)
def test_mac_format_is_irrelevant(written):
    assert build_magic_packet(written).hex() == ETH_PACKET_HEX
    assert normalize_mac(written) == ETH_MAC


@pytest.mark.parametrize("bad", ["00:00:5e:00:53", "gg:00:5e:00:53:01", "", "not a mac"])
def test_invalid_mac_rejected(bad):
    with pytest.raises(ConfigError):
        normalize_mac(bad)


async def test_send_to_no_targets_is_an_error():
    with pytest.raises(ApiError) as exc:
        await send_to_targets([])
    assert exc.value.code == "wake_failed"


async def test_send_reports_bytes_and_destination():
    target = WakeTarget(mac=ETH_MAC, broadcast="127.0.0.255", port=9)
    results = await send_to_targets([target])
    assert len(results) == 1
    assert results[0].to_dict() == {"mac": ETH_MAC, "via": "127.0.0.255:9", "bytes": 102}


async def test_partial_failure_still_succeeds():
    """One unroutable NIC must not prevent the other from being woken."""
    good = WakeTarget(mac=ETH_MAC, broadcast="127.0.0.255", port=9)
    bad = WakeTarget(mac=WIFI_MAC, broadcast="192.0.2.1", port=9)
    results = await send_to_targets([bad, good])
    assert any(r.mac == ETH_MAC for r in results)
