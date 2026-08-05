"""The pairing window state machine (PROTOCOL.md 9)."""

from __future__ import annotations

import asyncio

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from wol_unlock import pairing as P
from wol_unlock.crypto import canonical as C
from wol_unlock.errors import ApiError
from wol_unlock.pairing import PairingManager, PairingState


def make_proof(device_key, code: str, server_fp: str) -> tuple[str, str]:
    pubkey = device_key.public_key().public_bytes_raw()
    proof = device_key.sign(
        C.canonical_pair(
            code=code, device_pubkey_b64=C.b64u_encode(pubkey), server_fp=server_fp
        )
    )
    return C.b64u_encode(pubkey), C.b64u_encode(proof)


async def submit(manager, device_key, code, server_fp, name="iPhone"):
    pubkey_b64, proof_b64 = make_proof(device_key, code, server_fp)
    return await manager.submit(
        code=code, device_pubkey_b64=pubkey_b64, proof_b64=proof_b64,
        device_name=name, platform="ios",
    )


@pytest.fixture
def manager(test_config, identity, store) -> PairingManager:
    return PairingManager(test_config, identity, store)


class TestCodeHandling:
    def test_alphabet_excludes_look_alikes(self):
        for char in "ILOU":
            assert char not in P.CODE_ALPHABET
        assert len(P.CODE_ALPHABET) == 32  # 5 bits per character
        assert len(P.generate_code()) == P.CODE_LENGTH  # 40 bits total

    def test_codes_are_random(self):
        assert len({P.generate_code() for _ in range(200)}) > 190

    @pytest.mark.parametrize(
        "typed,expected",
        [
            ("k7m2-qx4b", "K7M2QX4B"),
            ("K7M2 QX4B", "K7M2QX4B"),
            ("K7MZQX4B", "K7MZQX4B"),
            ("IL0", "110"),      # I and L fold to 1
            ("o0o0", "0000"),    # O folds to 0
            ("U", "V"),          # U is not in the alphabet; V is the nearest glyph
        ],
    )
    def test_normalisation(self, typed, expected):
        assert P.normalize_code(typed) == expected

    def test_display_grouping(self):
        assert P.format_code("K7M2QX4B") == "K7M2-QX4B"


class TestWindowLifecycle:
    async def test_begin_returns_code_and_qr(self, manager, identity):
        opened = await manager.begin(60)
        assert len(opened["code"]) == P.CODE_LENGTH
        assert opened["qr"].startswith("wolunlock:1?")
        assert identity.fingerprint in opened["qr"]
        assert manager.state is PairingState.OPEN

    async def test_only_one_window_at_a_time(self, manager):
        await manager.begin(60)
        with pytest.raises(ApiError) as exc:
            await manager.begin(60)
        assert exc.value.code == "pairing_disabled"

    async def test_snapshot_never_leaks_the_code(self, manager):
        opened = await manager.begin(60)
        snapshot = manager.snapshot()
        assert opened["code"] not in str(snapshot)
        assert snapshot["active"] is True

    async def test_submit_without_window_refused(self, manager, device_key, identity):
        with pytest.raises(ApiError) as exc:
            await submit(manager, device_key, "AAAAAAAA", identity.fingerprint)
        assert exc.value.code == "pairing_disabled"

    async def test_cancel_closes(self, manager, device_key, identity):
        opened = await manager.begin(60)
        await manager.cancel()
        assert manager.state is PairingState.IDLE
        with pytest.raises(ApiError) as exc:
            await submit(manager, device_key, opened["code"], identity.fingerprint)
        assert exc.value.code == "pairing_disabled"


class TestEnrollment:
    async def test_happy_path(self, manager, device_key, identity, store):
        opened = await manager.begin(60)
        record = await submit(manager, device_key, opened["code"], identity.fingerprint)

        pubkey = device_key.public_key().public_bytes_raw()
        assert record.device_id == C.device_id_for(pubkey)
        assert record.pubkey == pubkey
        assert await store.get_device(record.device_id) is not None
        # The window is single-use: it closes on success.
        assert manager.state is PairingState.IDLE

    async def test_code_is_single_use(self, manager, device_key, identity):
        opened = await manager.begin(60)
        await submit(manager, device_key, opened["code"], identity.fingerprint)
        with pytest.raises(ApiError) as exc:
            await submit(manager, device_key, opened["code"], identity.fingerprint)
        assert exc.value.code == "pairing_disabled"

    async def test_wrong_code_counts_down_then_closes(self, manager, device_key, identity):
        opened = await manager.begin(60)
        for expected_remaining in (2, 1):
            with pytest.raises(ApiError) as exc:
                await submit(manager, device_key, "ZZZZZZZZ", identity.fingerprint)
            assert exc.value.code == "invalid_code"
            assert f"{expected_remaining} attempt" in exc.value.message

        with pytest.raises(ApiError) as exc:
            await submit(manager, device_key, "ZZZZZZZZ", identity.fingerprint)
        assert exc.value.code == "invalid_code"
        assert manager.state is PairingState.IDLE

        # The window is gone, so even the right code no longer works.
        with pytest.raises(ApiError) as exc:
            await submit(manager, device_key, opened["code"], identity.fingerprint)
        assert exc.value.code == "pairing_disabled"

    async def test_code_is_case_and_separator_insensitive(self, manager, device_key, identity):
        opened = await manager.begin(60)
        typed = P.format_code(opened["code"]).lower()
        pubkey_b64, proof_b64 = make_proof(
            device_key, P.normalize_code(typed), identity.fingerprint
        )
        record = await manager.submit(
            code=typed, device_pubkey_b64=pubkey_b64, proof_b64=proof_b64,
            device_name="iPhone", platform="ios",
        )
        assert record.device_id

    async def test_bad_proof_burns_the_window(self, manager, device_key, identity):
        """A correct code with a bad proof means the code reached someone who does
        not hold the key. Burn the window rather than let them retry."""
        opened = await manager.begin(60)
        other_key = Ed25519PrivateKey.generate()
        pubkey_b64 = C.b64u_encode(device_key.public_key().public_bytes_raw())
        _, wrong_proof = make_proof(other_key, opened["code"], identity.fingerprint)

        with pytest.raises(ApiError) as exc:
            await manager.submit(
                code=opened["code"], device_pubkey_b64=pubkey_b64, proof_b64=wrong_proof,
                device_name="iPhone", platform="ios",
            )
        assert exc.value.code == "invalid_signature"
        assert manager.state is PairingState.IDLE

    async def test_proof_bound_to_this_server(self, manager, device_key, identity):
        """A proof made for another PC must not enroll here."""
        opened = await manager.begin(60)
        pubkey_b64, proof_b64 = make_proof(device_key, opened["code"], "x" * 43)
        with pytest.raises(ApiError) as exc:
            await manager.submit(
                code=opened["code"], device_pubkey_b64=pubkey_b64, proof_b64=proof_b64,
                device_name="iPhone", platform="ios",
            )
        assert exc.value.code == "invalid_signature"

    async def test_proof_bound_to_this_code(self, manager, device_key, identity):
        opened = await manager.begin(60)
        pubkey_b64, proof_b64 = make_proof(device_key, "OTHERCOD", identity.fingerprint)
        with pytest.raises(ApiError) as exc:
            await manager.submit(
                code=opened["code"], device_pubkey_b64=pubkey_b64, proof_b64=proof_b64,
                device_name="iPhone", platform="ios",
            )
        assert exc.value.code == "invalid_signature"

    async def test_expired_window_rejected(self, manager, device_key, identity, monkeypatch):
        opened = await manager.begin(15)
        # Advance the monotonic clock the manager measures expiry against.
        base = P._monotonic()
        monkeypatch.setattr(P, "_monotonic", lambda: base + 60)
        with pytest.raises(ApiError) as exc:
            await submit(manager, device_key, opened["code"], identity.fingerprint)
        assert exc.value.code == "pairing_expired"
        assert manager.state is PairingState.IDLE

    @pytest.mark.parametrize("field", ["device_pubkey_b64", "proof_b64"])
    async def test_malformed_material_rejected(self, manager, device_key, identity, field):
        opened = await manager.begin(60)
        pubkey_b64, proof_b64 = make_proof(device_key, opened["code"], identity.fingerprint)
        kwargs = {"device_pubkey_b64": pubkey_b64, "proof_b64": proof_b64}
        kwargs[field] = "!!!not-base64!!!"
        with pytest.raises(ApiError) as exc:
            await manager.submit(
                code=opened["code"], device_name="iPhone", platform="ios", **kwargs
            )
        assert exc.value.code == "bad_request"


class TestApproval:
    @pytest.fixture
    def approving_manager(self, test_config, identity, store):
        from dataclasses import replace

        config = replace(
            test_config,
            pairing=replace(test_config.pairing, require_approval=True, approval_timeout_s=10),
        )
        return PairingManager(config, identity, store)

    async def test_approval_completes_enrollment(self, approving_manager, device_key, identity):
        opened = await approving_manager.begin(60)
        events: list[str] = []
        approving_manager.add_listener(lambda name, _data: events.append(name))

        task = asyncio.create_task(
            submit(approving_manager, device_key, opened["code"], identity.fingerprint)
        )
        await asyncio.sleep(0.05)
        assert approving_manager.state is PairingState.AWAITING_APPROVAL
        assert "pair.request" in events

        assert await approving_manager.resolve(True) is True
        record = await task
        assert record.device_id
        assert "pair.completed" in events

    async def test_denial_rejects(self, approving_manager, device_key, identity):
        opened = await approving_manager.begin(60)
        task = asyncio.create_task(
            submit(approving_manager, device_key, opened["code"], identity.fingerprint)
        )
        await asyncio.sleep(0.05)
        await approving_manager.resolve(False)

        with pytest.raises(ApiError) as exc:
            await task
        assert exc.value.code == "pairing_denied"
        assert approving_manager.state is PairingState.IDLE

    async def test_second_device_refused_while_awaiting(
        self, approving_manager, device_key, identity
    ):
        opened = await approving_manager.begin(60)
        task = asyncio.create_task(
            submit(approving_manager, device_key, opened["code"], identity.fingerprint)
        )
        await asyncio.sleep(0.05)

        other = Ed25519PrivateKey.generate()
        with pytest.raises(ApiError) as exc:
            await submit(approving_manager, other, opened["code"], identity.fingerprint)
        assert exc.value.code == "pairing_disabled"

        await approving_manager.resolve(True)
        await task

    async def test_timeout_closes_window(self, test_config, identity, store, device_key):
        """An operator who walks away must not leave an enrollment parked forever."""
        from dataclasses import replace

        config = replace(
            test_config,
            # Constructed directly rather than through from_toml, whose validator
            # enforces a 10s floor that would make this test slow.
            pairing=replace(test_config.pairing, require_approval=True, approval_timeout_s=1),
        )
        manager = PairingManager(config, identity, store)
        opened = await manager.begin(60)

        with pytest.raises(ApiError) as exc:
            await submit(manager, device_key, opened["code"], identity.fingerprint)
        assert exc.value.code == "pairing_timeout"
        assert manager.state is PairingState.IDLE
        assert await store.list_devices() == []


async def test_qr_payload_contains_everything_the_app_needs(test_config, identity):
    payload = P.build_qr_payload(test_config, identity, "K7M2QX4B")
    assert payload.startswith("wolunlock:1?")
    for expected in ("n=", "h=", "p=", f"f={identity.fingerprint}", "c=K7M2QX4B", "m=", "b="):
        assert expected in payload
    # Short enough to stay a comfortably scannable QR.
    assert len(payload) < 300
