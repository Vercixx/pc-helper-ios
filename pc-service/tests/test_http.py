"""End-to-end HTTP behaviour through the real middleware chain."""

from __future__ import annotations

import ipaddress
import json
import os
import time
from dataclasses import replace

import pytest
from aiohttp.test_utils import TestClient, TestServer
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from wol_unlock.crypto import canonical as C
from wol_unlock.crypto import verify as V
from wol_unlock.http import middleware as M
from wol_unlock.http.server import ROUTES, build_app
from wol_unlock.store import DeviceRecord


class SignedClient:
    """Test driver that signs like the phone does and verifies every response."""

    def __init__(self, client: TestClient, device_key, identity, device_id: str) -> None:
        self.client = client
        self.device_key = device_key
        self.identity = identity
        self.device_id = device_id
        self.last_nonce = ""

    def _verify_response_signature(self, response, raw: bytes, nonce_echo: str) -> None:
        signature = response.headers.get(V.HEADER_SERVER_SIGNATURE)
        assert signature, "every response must carry a server signature"
        message = C.canonical_response(
            status=response.status,
            nonce_echo=nonce_echo,
            body_sha256=C.sha256_b64u(raw),
            server_fp=self.identity.fingerprint,
        )
        Ed25519PublicKey.from_public_bytes(self.identity.public_raw).verify(
            C.b64u_decode(signature, expect_len=64), message
        )

    async def raw_get(self, path: str):
        response = await self.client.get(path)
        raw = await response.read()
        self._verify_response_signature(response, raw, "")
        return response, json.loads(raw)

    async def call(
        self, method: str, path: str, payload=None, *,
        nonce: str | None = None, timestamp: int | None = None,
        body_on_wire: bytes | None = None, device_id: str | None = None,
        server_fp: str | None = None, sign_with=None, headers: dict | None = None,
    ):
        body = b"" if payload is None else json.dumps(payload, separators=(",", ":")).encode()
        nonce = nonce or C.b64u_encode(os.urandom(16))
        timestamp = timestamp if timestamp is not None else int(time.time())
        device_id = device_id or self.device_id
        signer = sign_with or self.device_key

        signature = signer.sign(
            C.canonical_request(
                method=method, path=path.split("?")[0], timestamp=timestamp, nonce=nonce,
                body_sha256=C.sha256_b64u(body), device_id=device_id,
                server_fp=server_fp or self.identity.fingerprint,
            )
        )
        request_headers = {
            V.HEADER_VERSION: "1",
            V.HEADER_DEVICE: device_id,
            V.HEADER_TIMESTAMP: str(timestamp),
            V.HEADER_NONCE: nonce,
            V.HEADER_SIGNATURE: C.b64u_encode(signature),
            "Content-Type": "application/json",
        }
        request_headers.update(headers or {})

        response = await self.client.request(
            method, path, data=body if body_on_wire is None else body_on_wire,
            headers=request_headers,
        )
        raw = await response.read()
        self.last_nonce = nonce
        self._verify_response_signature(response, raw, nonce)
        return response, json.loads(raw)


@pytest.fixture
async def paired(context, device_key):
    """A context with one already-trusted device."""
    pubkey = device_key.public_key().public_bytes_raw()
    await context.store.upsert_device(
        device_id=C.device_id_for(pubkey), pubkey=pubkey,
        name="Test iPhone", platform="ios", now=int(time.time()),
    )
    return context


@pytest.fixture
async def api(paired, device_key, identity):
    server = TestServer(build_app(paired))
    client = TestClient(server)
    await client.start_server()
    signed = SignedClient(
        client, device_key, identity,
        C.device_id_for(device_key.public_key().public_bytes_raw()),
    )
    yield signed
    await client.close()


# --------------------------------------------------------------------------- #
# Route protection
# --------------------------------------------------------------------------- #

class TestRouteProtection:
    def test_public_paths_are_exactly_two(self):
        assert M.PUBLIC_PATHS == {"/v1/server-info", "/v1/pair"}

    def test_every_other_route_is_annotated_signed(self):
        for _, path, handler in ROUTES:
            expected = path not in M.PUBLIC_PATHS
            assert bool(getattr(handler, M.REQUIRES_AUTH, False)) is expected, path

    def test_build_app_rejects_mismatched_annotation(self, context, monkeypatch):
        """A new endpoint whose annotation disagrees with PUBLIC_PATHS must fail
        at startup rather than quietly serving unauthenticated traffic."""
        import wol_unlock.http.server as server_mod

        async def undecorated(_request):
            return {}

        monkeypatch.setattr(
            server_mod, "ROUTES", (("GET", "/v1/status", undecorated),)
        )
        with pytest.raises(RuntimeError, match="authentication"):
            build_app(context)

    @pytest.mark.parametrize(
        "method,path",
        [
            ("GET", "/v1/status"),
            ("POST", "/v1/wake"),
            ("POST", "/v1/unlock"),
            ("POST", "/v1/lock"),
        ],
    )
    async def test_protected_routes_reject_unsigned(self, api, method, path):
        """Regression: routes with no path variables produce an *empty*
        UrlMappingMatchInfo, which is falsy. A truthiness check here once made
        every fixed path public."""
        response = await api.client.request(method, path, data=b"{}")
        body = json.loads(await response.read())
        assert response.status == 400
        assert body["ok"] is False
        assert body["error"]["code"] == "bad_request"


# --------------------------------------------------------------------------- #
# Envelope and signing
# --------------------------------------------------------------------------- #

class TestEnvelope:
    async def test_server_info_is_public(self, api):
        response, body = await api.raw_get("/v1/server-info")
        assert response.status == 200
        assert body["data"]["fp"] == api.identity.fingerprint
        assert set(body["data"]) == {"v", "api", "name", "fp", "caps", "pair"}

    async def test_404_is_still_signed(self, api):
        response, body = await api.raw_get("/no/such/path")
        assert response.status == 404
        assert body["error"]["code"] == "bad_request"

    async def test_pre_auth_rejection_echoes_the_nonce(self, api):
        """Responses rejected before authentication must still be verifiable --
        SignedClient asserts the signature on every call, including this one."""
        response, body = await api.call("GET", "/v1/status?x=1")
        assert response.status == 400
        assert body["error"]["message"].startswith("query strings")

    async def test_method_not_allowed(self, api):
        response = await api.client.request("DELETE", "/v1/status")
        body = json.loads(await response.read())
        assert response.status == 405
        assert body["ok"] is False


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #

class TestAuthentication:
    async def test_happy_path(self, api):
        response, body = await api.call("GET", "/v1/status")
        assert response.status == 200
        assert body["data"]["name"] == "Test PC"

    async def test_replayed_nonce(self, api):
        nonce = C.b64u_encode(os.urandom(16))
        timestamp = int(time.time())
        first, _ = await api.call("GET", "/v1/status", nonce=nonce, timestamp=timestamp)
        assert first.status == 200
        second, body = await api.call("GET", "/v1/status", nonce=nonce, timestamp=timestamp)
        assert second.status == 401
        assert body["error"]["code"] == "replayed_nonce"

    @pytest.mark.parametrize("delta", [-3600, 3600])
    async def test_timestamp_window(self, api, delta):
        response, body = await api.call(
            "GET", "/v1/status", timestamp=int(time.time()) + delta
        )
        assert response.status == 401
        assert body["error"]["code"] == "timestamp_out_of_window"

    async def test_tampered_body(self, api):
        response, body = await api.call(
            "POST", "/v1/wake", {"target": "self"},
            body_on_wire=b'{"target":"self","evil":1}',
        )
        assert response.status == 401
        assert body["error"]["code"] == "invalid_signature"

    async def test_unknown_device(self, api, device_key):
        response, body = await api.call(
            "GET", "/v1/status", device_id=C.b64u_encode(b"\x09" * 16)
        )
        assert response.status == 401
        assert body["error"]["code"] == "unknown_device"

    async def test_revoked_device(self, api, paired):
        await paired.store.revoke_device(api.device_id, int(time.time()))
        response, body = await api.call("GET", "/v1/status")
        assert response.status == 403
        assert body["error"]["code"] == "device_revoked"

    async def test_cross_server_signature(self, api):
        response, body = await api.call("GET", "/v1/status", server_fp="z" * 43)
        assert response.status == 401
        assert body["error"]["code"] == "invalid_signature"

    async def test_wrong_key(self, api):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        response, body = await api.call(
            "GET", "/v1/status", sign_with=Ed25519PrivateKey.generate()
        )
        assert response.status == 401
        assert body["error"]["code"] == "invalid_signature"

    async def test_nonce_not_spent_on_failed_signature(self, api):
        """A nonce must only be consumed after the signature verifies, or an
        unauthenticated peer could burn a real device's nonces."""
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        nonce = C.b64u_encode(os.urandom(16))
        timestamp = int(time.time())
        bad, _ = await api.call(
            "GET", "/v1/status", nonce=nonce, timestamp=timestamp,
            sign_with=Ed25519PrivateKey.generate(),
        )
        assert bad.status == 401
        good, _ = await api.call("GET", "/v1/status", nonce=nonce, timestamp=timestamp)
        assert good.status == 200


class TestNetworkAllowlist:
    async def test_foreign_peer_rejected(self, context, device_key, identity):
        blocked = replace(
            context.config,
            http=replace(
                context.config.http,
                allowed_networks=(ipaddress.ip_network("10.99.0.0/24"),),
            ),
        )
        server = TestServer(build_app(replace(context, config=blocked)))
        client = TestClient(server)
        await client.start_server()
        try:
            response = await client.get("/v1/server-info")
            body = json.loads(await response.read())
            assert response.status == 403
            assert body["error"]["code"] == "forbidden_network"
        finally:
            await client.close()

    async def test_forwarded_for_header_is_ignored(self, api):
        """Trusting X-Forwarded-For would let any peer claim an allowed address."""
        response, _ = await api.call(
            "GET", "/v1/status", headers={"X-Forwarded-For": "10.99.0.1"}
        )
        assert response.status == 200


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #

class TestWake:
    async def test_wake_self(self, api):
        response, body = await api.call("POST", "/v1/wake", {"target": "self"})
        assert response.status == 200
        assert body["data"]["sent"][0]["bytes"] == 102

    async def test_mac_must_be_allowlisted(self, api):
        response, body = await api.call("POST", "/v1/wake", {"target": "aa:bb:cc:dd:ee:ff"})
        assert response.status == 403
        assert body["error"]["code"] == "not_allowed"

    async def test_broadcast_cannot_escape_the_lan(self, api):
        """Otherwise this endpoint is a signed relay for spraying UDP anywhere."""
        response, body = await api.call(
            "POST", "/v1/wake", {"target": "00:00:5e:00:53:01", "broadcast": "8.8.8.8"}
        )
        assert response.status == 403
        assert body["error"]["code"] == "not_allowed"

    async def test_port_override_validated(self, api):
        response, body = await api.call(
            "POST", "/v1/wake", {"target": "00:00:5e:00:53:01", "port": 99999}
        )
        assert response.status == 400


class TestUnlock:
    async def test_can_be_disabled_by_config(self, context, device_key, identity):
        disabled = replace(context.config, unlock_enabled=False)
        pubkey = device_key.public_key().public_bytes_raw()
        await context.store.upsert_device(
            device_id=C.device_id_for(pubkey), pubkey=pubkey,
            name="d", platform="ios", now=int(time.time()),
        )
        server = TestServer(build_app(replace(context, config=disabled)))
        client = TestClient(server)
        await client.start_server()
        signed = SignedClient(client, device_key, identity, C.device_id_for(pubkey))
        try:
            response, body = await signed.call("POST", "/v1/unlock", {"session_id": None})
            assert response.status == 403
            assert body["error"]["code"] == "not_allowed"
        finally:
            await client.close()

    async def test_malformed_session_id(self, api):
        response, body = await api.call("POST", "/v1/unlock", {"session_id": "; rm -rf /"})
        assert response.status == 400


class TestLock:
    async def test_can_be_disabled_by_config(self, context, device_key, identity):
        """Its own switch, not unlock's: turning unlock off is a decision about
        the risky direction and must not take the safe one away too."""
        disabled = replace(context.config, lock_enabled=False)
        pubkey = device_key.public_key().public_bytes_raw()
        await context.store.upsert_device(
            device_id=C.device_id_for(pubkey), pubkey=pubkey,
            name="d", platform="ios", now=int(time.time()),
        )
        server = TestServer(build_app(replace(context, config=disabled)))
        client = TestClient(server)
        await client.start_server()
        signed = SignedClient(client, device_key, identity, C.device_id_for(pubkey))
        try:
            response, body = await signed.call("POST", "/v1/lock", {"session_id": None})
            assert response.status == 403
            assert body["error"]["code"] == "not_allowed"
        finally:
            await client.close()

    async def test_disabling_unlock_leaves_lock_alone(self, context, device_key, identity):
        no_unlock = replace(context.config, unlock_enabled=False)
        assert "lock" in no_unlock.capabilities
        assert "unlock" not in no_unlock.capabilities

    async def test_malformed_session_id(self, api):
        response, body = await api.call("POST", "/v1/lock", {"session_id": "; rm -rf /"})
        assert response.status == 400


class TestPairEndpoint:
    async def test_requires_open_window(self, api):
        response = await api.client.post(
            "/v1/pair",
            json={"v": 1, "code": "AAAAAAAA", "device_pubkey": C.b64u_encode(b"\x00" * 32),
                  "proof": C.b64u_encode(b"\x00" * 64), "device_name": "x", "platform": "ios"},
        )
        body = json.loads(await response.read())
        assert response.status == 409
        assert body["error"]["code"] == "pairing_disabled"

    async def test_full_enrollment(self, api, paired):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        opened = await paired.pairing.begin(60)
        new_key = Ed25519PrivateKey.generate()
        pubkey = new_key.public_key().public_bytes_raw()
        proof = new_key.sign(
            C.canonical_pair(
                code=opened["code"], device_pubkey_b64=C.b64u_encode(pubkey),
                server_fp=api.identity.fingerprint,
            )
        )
        response = await api.client.post(
            "/v1/pair",
            json={"v": 1, "code": opened["code"], "device_pubkey": C.b64u_encode(pubkey),
                  "proof": C.b64u_encode(proof), "device_name": "New Phone", "platform": "ios"},
        )
        body = json.loads(await response.read())
        assert response.status == 200, body
        assert body["data"]["device_id"] == C.device_id_for(pubkey)
        assert body["data"]["server_pubkey"] == api.identity.public_b64

        stored: DeviceRecord | None = await paired.store.get_device(body["data"]["device_id"])
        assert stored is not None and stored.name == "New Phone"

    async def test_rejects_unknown_version(self, api, paired):
        await paired.pairing.begin(60)
        response = await api.client.post("/v1/pair", json={"v": 99, "code": "A"})
        assert response.status == 400


class TestBodyLimits:
    async def test_oversized_body_rejected(self, api):
        response = await api.client.post(
            "/v1/unlock", data=b"x" * 20000,
            headers={V.HEADER_VERSION: "1", V.HEADER_DEVICE: api.device_id,
                     V.HEADER_TIMESTAMP: str(int(time.time())),
                     V.HEADER_NONCE: C.b64u_encode(os.urandom(16)),
                     V.HEADER_SIGNATURE: C.b64u_encode(b"\x00" * 64)},
        )
        assert response.status in (400, 413)


async def test_audit_records_outcomes(api, paired):
    await api.call("GET", "/v1/status")
    await api.call("GET", "/v1/status", timestamp=1)
    rows = await paired.store.tail_audit(10)
    results = {row.result for row in rows}
    assert "ok" in results
    assert "timestamp_out_of_window" in results
    # Discovery noise is deliberately not audited.
    await api.raw_get("/v1/server-info")
    assert all("server-info" not in row.action for row in await paired.store.tail_audit(10))
