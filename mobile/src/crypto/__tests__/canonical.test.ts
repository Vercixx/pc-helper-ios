/**
 * Cross-language conformance.
 *
 * Every expected value here is copied from `docs/PROTOCOL.md` section 11 -- the
 * same constants asserted by the Python suite in
 * `pc-service/tests/test_canonical.py`. If these two suites ever disagree, the
 * phone and the PC have stopped speaking the same protocol.
 */

import * as ed from "@noble/ed25519";
import { sha512 } from "@noble/hashes/sha2.js";

import {
  b64uDecode,
  b64uEncode,
  canonicalPair,
  canonicalRequest,
  canonicalResponse,
  deviceIdFor,
  fingerprint,
  formatCode,
  normalizeCode,
  sha256B64u,
  toBytes,
} from "../canonical";

ed.hashes.sha512 = sha512;

const DEVICE_SEED = new Uint8Array(
  Array.from({ length: 32 }, (_, index) => index),
);
const SERVER_SEED = new Uint8Array(
  Array.from({ length: 32 }, (_, index) => index + 32),
);

const DEVICE_PUBKEY_B64 = "A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg";
const DEVICE_FP = "Vkdap1RjR0wChd9dvyvKtz2mUTWIOem3dIGy6rEHcIw";
const DEVICE_ID = "Vkdap1RjR0wChd9dvyvKtw";
const SERVER_PUBKEY_B64 = "Kay64UG8yvCyLhqU000LxzYeUm0L_hLIl5S8kyKWbdc";
const SERVER_FP = "JPbtasv-EAnAMNfKVnwzykgwkRSYI2tVYabIKr7F3ig";

const NONCE = "AAECAwQFBgcICQoLDA0ODw";
const TIMESTAMP = 1754390000;

const devicePub = ed.getPublicKey(DEVICE_SEED);
const serverPub = ed.getPublicKey(SERVER_SEED);

describe("identifier derivation", () => {
  it("matches the published public keys", () => {
    expect(b64uEncode(devicePub)).toBe(DEVICE_PUBKEY_B64);
    expect(b64uEncode(serverPub)).toBe(SERVER_PUBKEY_B64);
  });

  it("matches the published fingerprints and device id", () => {
    expect(fingerprint(devicePub)).toBe(DEVICE_FP);
    expect(deviceIdFor(devicePub)).toBe(DEVICE_ID);
    expect(fingerprint(serverPub)).toBe(SERVER_FP);
  });

  it("truncates digest bytes, not fingerprint characters", () => {
    // base64url packs 3 bytes into 4 characters, so the character at the
    // truncation boundary encodes bits the id does not contain.
    expect(DEVICE_ID.slice(0, 21)).toBe(DEVICE_FP.slice(0, 21));
    expect(DEVICE_ID[21]).not.toBe(DEVICE_FP[21]);
  });

  it("rejects keys of the wrong length", () => {
    expect(() => fingerprint(new Uint8Array(31))).toThrow();
    expect(() => deviceIdFor(new Uint8Array(33))).toThrow();
  });
});

describe("body hashing", () => {
  it("matches the published body hashes", () => {
    expect(sha256B64u(toBytes('{"session_id":null}'))).toBe(
      "ugKkY33US6fv1d7EpbDeofPdvlrqoTRVMiZiUtGq8f0",
    );
    expect(sha256B64u(new Uint8Array(0))).toBe(
      "47DEQpj8HBSa-_TImW-5JCeuQeRkm5NMpJWZG3hSuFU",
    );
  });
});

describe("canonical request", () => {
  const message = canonicalRequest({
    method: "POST",
    path: "/v1/unlock",
    timestamp: TIMESTAMP,
    nonce: NONCE,
    bodySha256: sha256B64u(toBytes('{"session_id":null}')),
    deviceId: DEVICE_ID,
    serverFp: SERVER_FP,
  });

  it("produces the exact bytes in the spec", () => {
    expect(new TextDecoder().decode(message)).toBe(
      "wol-unlock/v1/request\nPOST\n/v1/unlock\n1754390000\n" +
        "AAECAwQFBgcICQoLDA0ODw\nugKkY33US6fv1d7EpbDeofPdvlrqoTRVMiZiUtGq8f0\n" +
        "Vkdap1RjR0wChd9dvyvKtw\nJPbtasv-EAnAMNfKVnwzykgwkRSYI2tVYabIKr7F3ig\n",
    );
  });

  it("produces the published signature", () => {
    expect(b64uEncode(ed.sign(message, DEVICE_SEED))).toBe(
      "Fs2VYdYGCpDXJH0X6LtnfgzW1FNXitmbQKa3muzP_Py1CB3iCM-MUgWetLDQEMy4x-S3XkZepO4DX8mwsYHVDg",
    );
  });

  it("produces the published signature for an empty-body GET", () => {
    const status = canonicalRequest({
      method: "GET",
      path: "/v1/status",
      timestamp: TIMESTAMP,
      nonce: NONCE,
      bodySha256: sha256B64u(new Uint8Array(0)),
      deviceId: DEVICE_ID,
      serverFp: SERVER_FP,
    });
    expect(b64uEncode(ed.sign(status, DEVICE_SEED))).toBe(
      "fCaYE-4yelnVzRq0-VpCQ98jnlZUKAgfmotGaKNVqU9MsFlEPv5WeNl3VqBiLlQz-CMVB4Ei7wwOiMr1dbIUBg",
    );
  });

  it("refuses a field containing a newline", () => {
    expect(() =>
      canonicalRequest({
        method: "POST",
        path: "/v1/unlock\n1\nx",
        timestamp: 1,
        nonce: "n",
        bodySha256: "h",
        deviceId: "d",
        serverFp: "f",
      }),
    ).toThrow(/newline/);
  });
});

describe("canonical response", () => {
  it("produces the published signature and verifies", () => {
    const body =
      '{"ok":true,"ts":1754390000,"data":{"session_id":"1","was_locked":true,' +
      '"unlocked":true,"type":"wayland","desktop":"KDE","seat":"seat0"}}';
    expect(sha256B64u(toBytes(body))).toBe("mmGXuNks9F6NjLltYp8PGOUV29FKHmt5RF_p9GHMpf4");

    const message = canonicalResponse({
      status: 200,
      nonceEcho: NONCE,
      bodySha256: sha256B64u(toBytes(body)),
      serverFp: SERVER_FP,
    });
    const signature = ed.sign(message, SERVER_SEED);

    expect(b64uEncode(signature)).toBe(
      "Yvn1rC017_3ALuRNIpasxGz48SpkubMHhy5bYxXztabk_937gnqjoo7eZRTijyXb0Q8j0nx5v7jpBdnLwapuCQ",
    );
    // The client-side check that makes an unlock result trustworthy.
    expect(ed.verify(signature, message, serverPub)).toBe(true);
  });

  it("fails verification when the body is altered", () => {
    const message = canonicalResponse({
      status: 200,
      nonceEcho: NONCE,
      bodySha256: sha256B64u(toBytes('{"ok":true}')),
      serverFp: SERVER_FP,
    });
    const tampered = canonicalResponse({
      status: 200,
      nonceEcho: NONCE,
      bodySha256: sha256B64u(toBytes('{"ok":true,"evil":1}')),
      serverFp: SERVER_FP,
    });
    expect(ed.verify(ed.sign(message, SERVER_SEED), tampered, serverPub)).toBe(false);
  });

  it("fails verification when the nonce echo differs", () => {
    const message = canonicalResponse({
      status: 200,
      nonceEcho: NONCE,
      bodySha256: "h",
      serverFp: SERVER_FP,
    });
    const replayed = canonicalResponse({
      status: 200,
      nonceEcho: b64uEncode(new Uint8Array(16).fill(9)),
      bodySha256: "h",
      serverFp: SERVER_FP,
    });
    expect(ed.verify(ed.sign(message, SERVER_SEED), replayed, serverPub)).toBe(false);
  });
});

describe("pairing proof", () => {
  it("produces the published proof", () => {
    const message = canonicalPair({
      code: "K7M2QX4B",
      devicePubkeyB64: DEVICE_PUBKEY_B64,
      serverFp: SERVER_FP,
    });
    expect(b64uEncode(ed.sign(message, DEVICE_SEED))).toBe(
      "f6-18J9mt5LZMvLqis1xTCknnRdjz1kar75-O6TAaeIqfaWcc_GExPsMGAm8_GIaiERrGRzyhrA1g_H16WpeCw",
    );
  });

  it("is bound to one server and one code", () => {
    const base = { code: "K7M2QX4B", devicePubkeyB64: DEVICE_PUBKEY_B64, serverFp: SERVER_FP };
    const signature = ed.sign(canonicalPair(base), DEVICE_SEED);

    const otherServer = canonicalPair({ ...base, serverFp: "z".repeat(43) });
    const otherCode = canonicalPair({ ...base, code: "OTHERCOD" });

    expect(ed.verify(signature, otherServer, devicePub)).toBe(false);
    expect(ed.verify(signature, otherCode, devicePub)).toBe(false);
  });
});

describe("domain separation", () => {
  it("gives three distinct strings for identical field values", () => {
    const request = canonicalRequest({
      method: "POST",
      path: "/v1/unlock",
      timestamp: 1,
      nonce: "n",
      bodySha256: "h",
      deviceId: "d",
      serverFp: "f",
    });
    const response = canonicalResponse({
      status: 1,
      nonceEcho: "n",
      bodySha256: "h",
      serverFp: "f",
    });
    const pair = canonicalPair({ code: "C", devicePubkeyB64: "d", serverFp: "f" });

    const decoded = [request, response, pair].map((bytes) =>
      new TextDecoder().decode(bytes),
    );
    expect(new Set(decoded).size).toBe(3);
  });
});

describe("strict base64url", () => {
  it("round-trips every byte value", () => {
    for (let length = 0; length <= 34; length += 1) {
      const bytes = new Uint8Array(
        Array.from({ length }, (_, index) => (index * 37 + 11) % 256),
      );
      expect(b64uDecode(b64uEncode(bytes), length)).toEqual(bytes);
    }
  });

  it.each([
    ["padded", "AAECAwQFBgcICQoLDA0ODw=="],
    ["non-canonical trailing bits", "AAECAwQFBgcICQoLDA0ODx"],
    ["standard-alphabet character", "AAECAwQFBgcICQoLDA0OD/"],
    ["wrong length", "AAECAwQFBgcICQoLDA0OD"],
    ["impossible length", "A"],
    ["whitespace", "AAEC AwQFBgcICQoLDA0ODw"],
  ])("rejects %s", (_label, value) => {
    expect(() => b64uDecode(value, 16)).toThrow();
  });

  it("accepts an all-zero nonce", () => {
    // A legitimate, if improbable, draw. Uniqueness is the server's job.
    expect(b64uDecode("A".repeat(22), 16)).toEqual(new Uint8Array(16));
  });

  it("enforces the expected length", () => {
    expect(() => b64uDecode(b64uEncode(new Uint8Array(16)), 32)).toThrow(/expected 32/);
  });
});

describe("pairing code handling", () => {
  it.each([
    ["k7m2-qx4b", "K7M2QX4B"],
    ["K7M2 QX4B", "K7M2QX4B"],
    ["IL0", "110"],
    ["o0o0", "0000"],
    ["U", "V"],
  ])("normalises %s", (typed, expected) => {
    expect(normalizeCode(typed)).toBe(expected);
  });

  it("formats for display", () => {
    expect(formatCode("K7M2QX4B")).toBe("K7M2-QX4B");
    expect(formatCode("SHORT")).toBe("SHORT");
  });
});
