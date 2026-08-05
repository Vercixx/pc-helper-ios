"""The canonical strings must match PROTOCOL.md section 11 byte for byte.

If one of these fails, either the specification or an implementation has moved
and the iOS client will stop interoperating.
"""

from __future__ import annotations

import hashlib

import pytest

from wol_unlock.crypto import canonical as C

DEVICE_PUBKEY_B64 = "A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg"
DEVICE_FP = "Vkdap1RjR0wChd9dvyvKtz2mUTWIOem3dIGy6rEHcIw"
DEVICE_ID = "Vkdap1RjR0wChd9dvyvKtw"
SERVER_PUBKEY_B64 = "Kay64UG8yvCyLhqU000LxzYeUm0L_hLIl5S8kyKWbdc"
SERVER_FP = "JPbtasv-EAnAMNfKVnwzykgwkRSYI2tVYabIKr7F3ig"

NONCE = "AAECAwQFBgcICQoLDA0ODw"
TIMESTAMP = 1754390000
UNLOCK_BODY = b'{"session_id":null}'


def test_identifier_derivation(device_key, server_key):
    device_pub = device_key.public_key().public_bytes_raw()
    server_pub = server_key.public_key().public_bytes_raw()

    assert C.b64u_encode(device_pub) == DEVICE_PUBKEY_B64
    assert C.fingerprint(device_pub) == DEVICE_FP
    assert C.device_id_for(device_pub) == DEVICE_ID
    assert C.b64u_encode(server_pub) == SERVER_PUBKEY_B64
    assert C.fingerprint(server_pub) == SERVER_FP

    # device_id is the fingerprint's first 16 *bytes*, not its first 22
    # characters: base64url packs 3 bytes into 4 characters, so the character at
    # the truncation boundary encodes bits from a byte the id does not include.
    # Comparing the encoded strings would be wrong.
    assert C.b64u_decode(DEVICE_ID, expect_len=16) == C.b64u_decode(DEVICE_FP)[:16]
    assert DEVICE_ID[:21] == DEVICE_FP[:21]
    assert DEVICE_ID[21] != DEVICE_FP[21]


def test_body_hashes():
    assert C.sha256_b64u(UNLOCK_BODY) == "ugKkY33US6fv1d7EpbDeofPdvlrqoTRVMiZiUtGq8f0"
    assert C.sha256_b64u(b"") == "47DEQpj8HBSa-_TImW-5JCeuQeRkm5NMpJWZG3hSuFU"


def test_canonical_request_bytes():
    message = C.canonical_request(
        method="POST",
        path="/v1/unlock",
        timestamp=TIMESTAMP,
        nonce=NONCE,
        body_sha256=C.sha256_b64u(UNLOCK_BODY),
        device_id=DEVICE_ID,
        server_fp=SERVER_FP,
    )
    assert message == (
        b"wol-unlock/v1/request\nPOST\n/v1/unlock\n1754390000\n"
        b"AAECAwQFBgcICQoLDA0ODw\nugKkY33US6fv1d7EpbDeofPdvlrqoTRVMiZiUtGq8f0\n"
        b"Vkdap1RjR0wChd9dvyvKtw\nJPbtasv-EAnAMNfKVnwzykgwkRSYI2tVYabIKr7F3ig\n"
    )
    assert (
        hashlib.sha256(message).hexdigest()
        == "ba3ab0822e3f159cef71db185c915be8a74591e5dcfbde4704907b53d9500a11"
    )


def test_request_signature_vector(device_key):
    message = C.canonical_request(
        method="POST", path="/v1/unlock", timestamp=TIMESTAMP, nonce=NONCE,
        body_sha256=C.sha256_b64u(UNLOCK_BODY), device_id=DEVICE_ID, server_fp=SERVER_FP,
    )
    assert C.b64u_encode(device_key.sign(message)) == (
        "Fs2VYdYGCpDXJH0X6LtnfgzW1FNXitmbQKa3muzP_Py1CB3iCM-MUgWetLDQEMy4x-S3XkZepO4DX8mwsYHVDg"
    )


def test_status_signature_vector(device_key):
    message = C.canonical_request(
        method="GET", path="/v1/status", timestamp=TIMESTAMP, nonce=NONCE,
        body_sha256=C.sha256_b64u(b""), device_id=DEVICE_ID, server_fp=SERVER_FP,
    )
    assert C.b64u_encode(device_key.sign(message)) == (
        "fCaYE-4yelnVzRq0-VpCQ98jnlZUKAgfmotGaKNVqU9MsFlEPv5WeNl3VqBiLlQz-CMVB4Ei7wwOiMr1dbIUBg"
    )


def test_response_signature_vector(server_key):
    body = (
        b'{"ok":true,"ts":1754390000,"data":{"session_id":"1","was_locked":true,'
        b'"unlocked":true,"type":"wayland","desktop":"KDE","seat":"seat0"}}'
    )
    assert C.sha256_b64u(body) == "mmGXuNks9F6NjLltYp8PGOUV29FKHmt5RF_p9GHMpf4"
    message = C.canonical_response(
        status=200, nonce_echo=NONCE, body_sha256=C.sha256_b64u(body), server_fp=SERVER_FP
    )
    assert C.b64u_encode(server_key.sign(message)) == (
        "Yvn1rC017_3ALuRNIpasxGz48SpkubMHhy5bYxXztabk_937gnqjoo7eZRTijyXb0Q8j0nx5v7jpBdnLwapuCQ"
    )


def test_pair_proof_vector(device_key):
    message = C.canonical_pair(
        code="K7M2QX4B", device_pubkey_b64=DEVICE_PUBKEY_B64, server_fp=SERVER_FP
    )
    assert message == (
        b"wol-unlock/v1/pair\nK7M2QX4B\n"
        b"A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg\n"
        b"JPbtasv-EAnAMNfKVnwzykgwkRSYI2tVYabIKr7F3ig\n"
    )
    assert C.b64u_encode(device_key.sign(message)) == (
        "f6-18J9mt5LZMvLqis1xTCknnRdjz1kar75-O6TAaeIqfaWcc_GExPsMGAm8_GIaiERrGRzyhrA1g_H16WpeCw"
    )


def test_domain_separation_differs():
    """The same field values under different domains must not collide."""
    request = C.canonical_request(
        method="POST", path="/v1/unlock", timestamp=1, nonce="n",
        body_sha256="h", device_id="d", server_fp="f",
    )
    response = C.canonical_response(status=1, nonce_echo="n", body_sha256="h", server_fp="f")
    pair = C.canonical_pair(code="C", device_pubkey_b64="d", server_fp="f")
    assert len({request, response, pair}) == 3


def test_newline_in_field_is_rejected():
    """Field separation has no length prefixes, so an embedded newline would let
    one field impersonate several."""
    with pytest.raises(ValueError, match="newline"):
        C.canonical_request(
            method="POST", path="/v1/unlock\n1\nx", timestamp=1, nonce="n",
            body_sha256="h", device_id="d", server_fp="f",
        )


class TestStrictBase64Url:
    def test_round_trip(self):
        raw = bytes(range(16))
        assert C.b64u_decode(C.b64u_encode(raw), expect_len=16) == raw

    @pytest.mark.parametrize(
        "value",
        [
            "AAECAwQFBgcICQoLDA0ODw==",  # padded
            "AAECAwQFBgcICQoLDA0ODx",    # non-canonical trailing bits
            "AAECAwQFBgcICQoLDA0OD/",    # standard-alphabet character
            "AAECAwQFBgcICQoLDA0OD",     # wrong length
            "A",                          # impossible length
            "AAEC AwQFBgcICQoLDA0ODw",   # whitespace
            "",                           # empty
        ],
    )
    def test_rejects(self, value):
        with pytest.raises(ValueError):
            C.b64u_decode(value, expect_len=16)

    def test_length_enforced(self):
        with pytest.raises(ValueError, match="expected 32 bytes"):
            C.b64u_decode(C.b64u_encode(b"\x00" * 16), expect_len=32)
