"""Device records and the replay cache."""

from __future__ import annotations

from pathlib import Path

from wol_unlock.store import Store

PUBKEY = b"\x01" * 32
DEVICE_ID = "Vkdap1RjR0wChd9dvyvKtw"


async def test_upsert_and_fetch(store: Store):
    record = await store.upsert_device(
        device_id=DEVICE_ID, pubkey=PUBKEY, name="iPhone", platform="ios", now=100
    )
    assert record.name == "iPhone"
    assert not record.revoked
    assert (await store.get_device(DEVICE_ID)).pubkey == PUBKEY
    assert await store.get_device("nope") is None


async def test_revoke_then_repair_restores_access(store: Store):
    await store.upsert_device(
        device_id=DEVICE_ID, pubkey=PUBKEY, name="iPhone", platform="ios", now=100
    )
    assert await store.revoke_device(DEVICE_ID, 200) is True
    assert (await store.get_device(DEVICE_ID)).revoked is True
    # Revoking twice is a no-op, not an error.
    assert await store.revoke_device(DEVICE_ID, 201) is False

    # Pairing again clears the revocation. This still costs a fresh code and a
    # fresh local approval, so it grants nothing a first pairing would not.
    await store.upsert_device(
        device_id=DEVICE_ID, pubkey=PUBKEY, name="iPhone", platform="ios", now=300
    )
    assert (await store.get_device(DEVICE_ID)).revoked is False


async def test_delete_removes_device_and_its_nonces(store: Store):
    await store.upsert_device(
        device_id=DEVICE_ID, pubkey=PUBKEY, name="iPhone", platform="ios", now=100
    )
    await store.consume_nonce(DEVICE_ID, "abc", 999)
    assert await store.delete_device(DEVICE_ID) is True
    assert await store.get_device(DEVICE_ID) is None
    assert await store.count_nonces() == 0


class TestNonceReplay:
    async def test_second_use_is_rejected(self, store: Store):
        assert await store.consume_nonce(DEVICE_ID, "n1", 999) is True
        assert await store.consume_nonce(DEVICE_ID, "n1", 999) is False

    async def test_scoped_per_device(self, store: Store):
        """Two devices drawing the same random nonce must not collide."""
        assert await store.consume_nonce("device-a", "same", 999) is True
        assert await store.consume_nonce("device-b", "same", 999) is True

    async def test_survives_restart(self, state_dir: Path):
        """The whole point of persisting nonces.

        An in-memory cache would reopen a `timestamp_skew_s`-wide replay window on
        every restart -- exactly when an attacker holding a captured request would
        try one.
        """
        path = state_dir / "restart.db"
        first = await Store.open(path)
        assert await first.consume_nonce(DEVICE_ID, "survivor", 999) is True
        await first.close()

        second = await Store.open(path)
        assert await second.consume_nonce(DEVICE_ID, "survivor", 999) is False
        await second.close()

    async def test_sweep_frees_only_expired(self, store: Store):
        await store.consume_nonce(DEVICE_ID, "old", 100)
        await store.consume_nonce(DEVICE_ID, "new", 500)
        assert await store.sweep_nonces(200) == 1
        assert await store.consume_nonce(DEVICE_ID, "old", 900) is True
        assert await store.consume_nonce(DEVICE_ID, "new", 900) is False


async def test_audit_is_bounded(store: Store):
    for index in range(50):
        await store.add_audit(ts=index, action="GET /v1/status", result="ok")
    assert len(await store.tail_audit(1000)) == 50
    await store.prune_audit(keep=10)
    remaining = await store.tail_audit(1000)
    assert len(remaining) == 10
    # Newest rows are the ones kept.
    assert remaining[0].ts == 49


async def test_tail_audit_limit_is_clamped(store: Store):
    await store.add_audit(ts=1, action="x", result="ok")
    assert len(await store.tail_audit(0)) == 1
    assert len(await store.tail_audit(10**9)) == 1
