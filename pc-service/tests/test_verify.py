"""Header parsing, freshness window, and signature verification."""

from __future__ import annotations

import pytest

from wol_unlock.crypto import canonical as C
from wol_unlock.crypto import verify as V
from wol_unlock.errors import ApiError

from test_canonical import DEVICE_ID, NONCE, SERVER_FP, TIMESTAMP


def headers(**overrides) -> dict[str, str]:
    base = {
        V.HEADER_VERSION: "1",
        V.HEADER_DEVICE: DEVICE_ID,
        V.HEADER_TIMESTAMP: str(TIMESTAMP),
        V.HEADER_NONCE: NONCE,
        V.HEADER_SIGNATURE: C.b64u_encode(b"\x00" * 64),
    }
    base.update({k: v for k, v in overrides.items() if v is not None})
    for key, value in overrides.items():
        if value is None:
            base.pop(key, None)
    return base


class TestParseAuthHeaders:
    def test_accepts_well_formed(self):
        parsed = V.parse_auth_headers(headers())
        assert parsed.device_id == DEVICE_ID
        assert parsed.timestamp == TIMESTAMP
        assert parsed.nonce == NONCE
        assert len(parsed.signature) == 64

    @pytest.mark.parametrize(
        "field",
        [
            V.HEADER_VERSION,
            V.HEADER_DEVICE,
            V.HEADER_TIMESTAMP,
            V.HEADER_NONCE,
            V.HEADER_SIGNATURE,
        ],
    )
    def test_missing_header_rejected(self, field):
        with pytest.raises(ApiError) as exc:
            V.parse_auth_headers(headers(**{field: None}))
        assert exc.value.code == "bad_request"

    def test_unsupported_version_rejected(self):
        with pytest.raises(ApiError, match="unsupported protocol version"):
            V.parse_auth_headers(headers(**{V.HEADER_VERSION: "2"}))

    @pytest.mark.parametrize(
        "timestamp", ["+1754390000", " 1754390000x", "01754390000", "-1", "1e9", ""]
    )
    def test_non_canonical_timestamp_rejected(self, timestamp):
        """The signed canonical string contains one exact spelling of the
        timestamp; accepting variants would let one instant be presented
        several ways."""
        with pytest.raises(ApiError):
            V.parse_auth_headers(headers(**{V.HEADER_TIMESTAMP: timestamp}))

    @pytest.mark.parametrize("nonce", ["short", NONCE + "A", NONCE[:-1] + "=", "!" * 22])
    def test_bad_nonce_rejected(self, nonce):
        with pytest.raises(ApiError):
            V.parse_auth_headers(headers(**{V.HEADER_NONCE: nonce}))

    def test_all_zero_nonce_is_syntactically_valid(self):
        """It is a legitimate (if improbable) draw. Uniqueness is the store's
        job, not the parser's."""
        parsed = V.parse_auth_headers(headers(**{V.HEADER_NONCE: "A" * 22}))
        assert parsed.nonce == "A" * 22

    def test_bad_signature_length_rejected(self):
        with pytest.raises(ApiError, match="malformed signature"):
            V.parse_auth_headers(headers(**{V.HEADER_SIGNATURE: C.b64u_encode(b"\x00" * 63)}))

    def test_bad_device_id_rejected(self):
        with pytest.raises(ApiError, match="malformed device id"):
            V.parse_auth_headers(headers(**{V.HEADER_DEVICE: "not-a-device-id-xxxxxx"}))


class TestTimestampWindow:
    @pytest.mark.parametrize("offset", [0, 29, -29, 30, -30])
    def test_inside_window_accepted(self, offset):
        V.check_timestamp(1000 + offset, 1000, 30)

    @pytest.mark.parametrize("offset", [31, -31, 3600, -3600])
    def test_outside_window_rejected(self, offset):
        with pytest.raises(ApiError) as exc:
            V.check_timestamp(1000 + offset, 1000, 30)
        assert exc.value.code == "timestamp_out_of_window"


class TestSignatureVerification:
    def _args(self, device_key, server_fp=SERVER_FP, body=b'{"session_id":null}'):
        return dict(
            pubkey_raw=device_key.public_key().public_bytes_raw(),
            method="POST",
            path="/v1/unlock",
            timestamp=TIMESTAMP,
            nonce=NONCE,
            body=body,
            device_id=DEVICE_ID,
            server_fp=server_fp,
        )

    def _sign(self, device_key, **kwargs):
        args = self._args(device_key, **kwargs)
        return device_key.sign(
            C.canonical_request(
                method=args["method"], path=args["path"], timestamp=args["timestamp"],
                nonce=args["nonce"], body_sha256=C.sha256_b64u(args["body"]),
                device_id=args["device_id"], server_fp=args["server_fp"],
            )
        )

    def test_valid_signature_accepted(self, device_key):
        V.verify_request_signature(
            **self._args(device_key), signature=self._sign(device_key)
        )

    def test_flipped_bit_rejected(self, device_key):
        signature = bytearray(self._sign(device_key))
        signature[0] ^= 0x01
        with pytest.raises(ApiError) as exc:
            V.verify_request_signature(**self._args(device_key), signature=bytes(signature))
        assert exc.value.code == "invalid_signature"

    def test_body_tampering_rejected(self, device_key):
        """Signature was made over the original body; a different body must fail."""
        signature = self._sign(device_key)
        args = self._args(device_key)
        args["body"] = b'{"session_id":null,"evil":1}'
        with pytest.raises(ApiError) as exc:
            V.verify_request_signature(**args, signature=signature)
        assert exc.value.code == "invalid_signature"

    def test_cross_server_replay_rejected(self, device_key):
        """A request signed for PC-A must not verify against PC-B, even though
        the same device is legitimately paired with both."""
        signature = self._sign(device_key, server_fp=SERVER_FP)
        args = self._args(device_key, server_fp="a" * 43)
        with pytest.raises(ApiError) as exc:
            V.verify_request_signature(**args, signature=signature)
        assert exc.value.code == "invalid_signature"

    def test_path_substitution_rejected(self, device_key):
        """A signature captured for /v1/status must not authorise /v1/unlock."""
        signature = device_key.sign(
            C.canonical_request(
                method="GET", path="/v1/status", timestamp=TIMESTAMP, nonce=NONCE,
                body_sha256=C.sha256_b64u(b""), device_id=DEVICE_ID, server_fp=SERVER_FP,
            )
        )
        args = self._args(device_key, body=b"")
        args["method"] = "GET"
        with pytest.raises(ApiError):
            V.verify_request_signature(**args, signature=signature)

    def test_declared_body_hash_mismatch_caught_early(self, device_key):
        with pytest.raises(ApiError) as exc:
            V.verify_request_signature(
                **self._args(device_key),
                signature=self._sign(device_key),
                expected_body_sha256="not-the-real-hash",
            )
        assert exc.value.code == "body_hash_mismatch"
