/**
 * Canonical byte strings and encodings for protocol v1.
 *
 * This is the mirror of `pc-service/src/wol_unlock/crypto/canonical.py`. Every
 * construction here is pinned by the shared vectors in `docs/PROTOCOL.md`
 * section 11 and asserted by `src/crypto/__tests__/canonical.test.ts`. Changing
 * anything in this file is a protocol break.
 *
 * base64url is implemented here rather than borrowed from `btoa`/`Buffer`:
 * neither is reliably present in React Native, and a strict decoder is a
 * security requirement, not a nicety -- see `b64uDecode`.
 */

import { sha256 } from "@noble/hashes/sha2.js";
import { utf8ToBytes } from "@noble/hashes/utils.js";

export const DOMAIN_REQUEST = "wol-unlock/v1/request";
export const DOMAIN_RESPONSE = "wol-unlock/v1/response";
export const DOMAIN_PAIR = "wol-unlock/v1/pair";

export const NONCE_BYTES = 16;
export const NONCE_CHARS = 22;
export const SIGNATURE_BYTES = 64;
export const PUBKEY_BYTES = 32;
export const SEED_BYTES = 32;
export const DEVICE_ID_CHARS = 22;
export const FINGERPRINT_CHARS = 43;

const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

const LOOKUP: Record<string, number> = {};
for (let i = 0; i < ALPHABET.length; i += 1) {
  LOOKUP[ALPHABET[i]!] = i;
}

/** base64url encode, no padding. */
export function b64uEncode(bytes: Uint8Array): string {
  let out = "";
  for (let i = 0; i < bytes.length; i += 3) {
    const b0 = bytes[i]!;
    const b1 = bytes[i + 1];
    const b2 = bytes[i + 2];

    out += ALPHABET[b0 >> 2];
    out += ALPHABET[((b0 & 0x03) << 4) | ((b1 ?? 0) >> 4)];
    if (b1 === undefined) break;
    out += ALPHABET[((b1 & 0x0f) << 2) | ((b2 ?? 0) >> 6)];
    if (b2 === undefined) break;
    out += ALPHABET[b2 & 0x3f];
  }
  return out;
}

/**
 * Strict base64url decode.
 *
 * Rejects padding, non-alphabet characters, impossible lengths, and
 * non-canonical encodings (trailing bits a correct encoder would have zeroed).
 * Leniency here would let the same key or signature be spelled several ways,
 * turning an identifier into a set rather than a value.
 */
export function b64uDecode(text: string, expectLen?: number): Uint8Array {
  if (typeof text !== "string" || !/^[A-Za-z0-9_-]*$/.test(text)) {
    throw new Error("not base64url");
  }
  if (text.length % 4 === 1) {
    throw new Error("impossible base64url length");
  }

  const out = new Uint8Array(Math.floor((text.length * 3) / 4));
  let outIndex = 0;

  for (let i = 0; i < text.length; i += 4) {
    const c0 = LOOKUP[text[i]!]!;
    const c1 = LOOKUP[text[i + 1]!];
    if (c1 === undefined) throw new Error("truncated base64url group");
    const c2 = LOOKUP[text[i + 2]!];
    const c3 = LOOKUP[text[i + 3]!];

    out[outIndex++] = (c0 << 2) | (c1 >> 4);
    if (c2 === undefined) break;
    out[outIndex++] = ((c1 & 0x0f) << 4) | (c2 >> 2);
    if (c3 === undefined) break;
    out[outIndex++] = ((c2 & 0x03) << 6) | c3;
  }

  const result = out.subarray(0, outIndex);
  if (expectLen !== undefined && result.length !== expectLen) {
    throw new Error(`expected ${expectLen} bytes, got ${result.length}`);
  }
  // Round-trip check rejects non-canonical trailing bits.
  if (b64uEncode(result) !== text) {
    throw new Error("non-canonical base64url");
  }
  return result;
}

/** b64u(SHA-256(bytes)) -- the body-hash form used in canonical strings. */
export function sha256B64u(data: Uint8Array): string {
  return b64uEncode(sha256(data));
}

/** UTF-8 encode. The canonical strings are ASCII, but bodies may not be. */
export function toBytes(text: string): Uint8Array {
  return utf8ToBytes(text);
}

/** Public identity of a key: b64u(SHA-256(pubkey)), 43 characters. */
export function fingerprint(pubkey: Uint8Array): string {
  if (pubkey.length !== PUBKEY_BYTES) {
    throw new Error("public key must be 32 raw bytes");
  }
  return b64uEncode(sha256(pubkey));
}

/**
 * Device identifier: b64u(SHA-256(pubkey)[0..16]), 22 characters.
 *
 * Note this truncates the digest *bytes* before encoding, so it is not simply
 * the first 22 characters of the fingerprint.
 */
export function deviceIdFor(pubkey: Uint8Array): string {
  if (pubkey.length !== PUBKEY_BYTES) {
    throw new Error("public key must be 32 raw bytes");
  }
  return b64uEncode(sha256(pubkey).subarray(0, 16));
}

function field(name: string, value: string | number): string {
  const text = String(value);
  if (text.includes("\n") || text.includes("\r")) {
    throw new Error(`canonical field '${name}' contains a newline`);
  }
  return text;
}

/** Bytes the device signs for an authenticated request (PROTOCOL.md 2.1). */
export function canonicalRequest(input: {
  method: string;
  path: string;
  timestamp: number;
  nonce: string;
  bodySha256: string;
  deviceId: string;
  serverFp: string;
}): Uint8Array {
  const parts = [
    DOMAIN_REQUEST,
    field("method", input.method).toUpperCase(),
    field("path", input.path),
    field("timestamp", input.timestamp),
    field("nonce", input.nonce),
    field("bodySha256", input.bodySha256),
    field("deviceId", input.deviceId),
    field("serverFp", input.serverFp),
  ];
  return toBytes(parts.join("\n") + "\n");
}

/** Bytes the server signs for a response (PROTOCOL.md 2.2). */
export function canonicalResponse(input: {
  status: number;
  nonceEcho: string;
  bodySha256: string;
  serverFp: string;
}): Uint8Array {
  const parts = [
    DOMAIN_RESPONSE,
    field("status", input.status),
    field("nonceEcho", input.nonceEcho),
    field("bodySha256", input.bodySha256),
    field("serverFp", input.serverFp),
  ];
  return toBytes(parts.join("\n") + "\n");
}

/** Bytes the enrolling device signs as its pairing proof (PROTOCOL.md 2.3). */
export function canonicalPair(input: {
  code: string;
  devicePubkeyB64: string;
  serverFp: string;
}): Uint8Array {
  const parts = [
    DOMAIN_PAIR,
    field("code", input.code).toUpperCase(),
    field("devicePubkey", input.devicePubkeyB64),
    field("serverFp", input.serverFp),
  ];
  return toBytes(parts.join("\n") + "\n");
}

/** Crockford base32 minus I, L, O and U -- the pairing code alphabet. */
export const CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
export const CODE_LENGTH = 8;

const FOLD: Record<string, string> = { I: "1", L: "1", O: "0", U: "V" };

/** Upper-case, strip grouping punctuation, fold look-alike characters. */
export function normalizeCode(value: string): string {
  return value
    .toUpperCase()
    .split("")
    .filter((ch) => /[A-Z0-9]/.test(ch))
    .map((ch) => FOLD[ch] ?? ch)
    .join("");
}

/** "K7M2QX4B" -> "K7M2-QX4B", for display only. */
export function formatCode(code: string): string {
  return code.length === CODE_LENGTH ? `${code.slice(0, 4)}-${code.slice(4)}` : code;
}
