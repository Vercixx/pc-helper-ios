/**
 * Signed HTTP client.
 *
 * Two invariants this module is responsible for:
 *
 *  1. Every authenticated request is signed over the canonical string in
 *     PROTOCOL.md 2.1, including the server's fingerprint -- so a captured
 *     request is useless against any other PC.
 *  2. Every response is verified against the server key pinned at pairing time
 *     *before* its body is parsed or returned. Without this, a LAN attacker
 *     could simply answer `{"unlocked": true}` on the PC's behalf.
 */

import * as Crypto from "expo-crypto";

import {
  NONCE_BYTES,
  SIGNATURE_BYTES,
  b64uDecode,
  b64uEncode,
  canonicalPair,
  canonicalRequest,
  canonicalResponse,
  fingerprint,
  normalizeCode,
  sha256B64u,
  toBytes,
} from "@/crypto/canonical";
import { type KeyStorageMode, ed, signWithDeviceKey } from "@/crypto/keys";
import type { LinkedPC } from "@/state/types";

import {
  ApiError,
  type ApiEnvelope,
  type PairResponse,
  type ServerInfo,
  type StatusResponse,
  type LockResponse,
  type UnlockResponse,
  type WakeResponse,
} from "./types";

/** Long enough for a sleepy Wi-Fi radio, short enough not to hang the UI. */
const DEFAULT_TIMEOUT_MS = 6000;
/** `/v1/pair` parks while the operator approves at the PC. */
const PAIR_TIMEOUT_MS = 75_000;

export type Endpoint = { host: string; port: number };

function baseUrl({ host, port }: Endpoint): string {
  return `http://${host}:${port}`;
}

function newNonce(): string {
  return b64uEncode(Crypto.getRandomBytes(NONCE_BYTES));
}

async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new ApiError("unreachable", message);
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Verify `X-WU-Server-Signature` over the exact bytes received.
 *
 * `nonceEcho` must be the nonce we sent, which ties this response to this
 * request and stops a recorded reply being replayed against a later one.
 */
function verifyServerSignature(
  response: Response,
  rawBody: string,
  nonceEcho: string,
  serverPubKeyB64: string,
): void {
  const header = response.headers.get("X-WU-Server-Signature");
  if (!header) {
    throw new ApiError(
      "unsigned_response",
      "the PC's reply carried no signature",
      response.status,
    );
  }

  let signature: Uint8Array;
  let serverPubKey: Uint8Array;
  try {
    signature = b64uDecode(header, SIGNATURE_BYTES);
    serverPubKey = b64uDecode(serverPubKeyB64, 32);
  } catch {
    throw new ApiError("bad_server_signature", "malformed signature", response.status);
  }

  // The fingerprint in the canonical string is derived from the key we pinned at
  // pairing time, never read off the wire -- otherwise an impostor could simply
  // assert its own identity and sign consistently with it.
  const signed = canonicalResponse({
    status: response.status,
    nonceEcho,
    bodySha256: sha256B64u(toBytes(rawBody)),
    serverFp: fingerprint(serverPubKey),
  });

  if (!ed.verify(signature, signed, serverPubKey)) {
    throw new ApiError(
      "bad_server_signature",
      "the reply was not signed by this PC",
      response.status,
    );
  }
}

function parseEnvelope<T>(rawBody: string, status: number): T {
  let parsed: ApiEnvelope<T>;
  try {
    parsed = JSON.parse(rawBody) as ApiEnvelope<T>;
  } catch {
    throw new ApiError("malformed_response", "the PC sent something that isn't JSON", status);
  }
  if (!parsed || typeof parsed !== "object" || !("ok" in parsed)) {
    throw new ApiError("malformed_response", "unexpected response shape", status);
  }
  if (!parsed.ok) {
    const error = parsed.error ?? { code: "internal_error", message: "unknown error" };
    throw new ApiError(error.code as never, error.message, status);
  }
  return parsed.data;
}

/**
 * A signed call to a paired PC.
 *
 * Never prompts for biometrics: that gate is applied by the caller, on the
 * action, so that a background status poll cannot trigger a Face ID sheet.
 */
async function signedCall<T>(
  pc: LinkedPC,
  endpoint: Endpoint,
  method: "GET" | "POST",
  path: string,
  payload?: unknown,
  options: { timeoutMs?: number } = {},
): Promise<T> {
  const bodyText = payload === undefined ? "" : JSON.stringify(payload);
  const nonce = newNonce();
  const timestamp = Math.floor(Date.now() / 1000);

  const message = canonicalRequest({
    method,
    path,
    timestamp,
    nonce,
    bodySha256: sha256B64u(toBytes(bodyText)),
    deviceId: pc.deviceId,
    serverFp: pc.serverFp,
  });

  const signature = await signWithDeviceKey(pc.keyAlias, message, pc.keyMode);

  const response = await fetchWithTimeout(
    `${baseUrl(endpoint)}${path}`,
    {
      method,
      headers: {
        "X-WU-Version": "1",
        "X-WU-Device": pc.deviceId,
        "X-WU-Timestamp": String(timestamp),
        "X-WU-Nonce": nonce,
        "X-WU-Signature": b64uEncode(signature),
        "Content-Type": "application/json",
      },
      ...(method === "POST" ? { body: bodyText } : {}),
    },
    options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
  );

  const rawBody = await response.text();
  verifyServerSignature(response, rawBody, nonce, pc.serverPubKey);
  return parseEnvelope<T>(rawBody, response.status);
}

// --------------------------------------------------------------------------- //
// Public API
// --------------------------------------------------------------------------- //

/**
 * Unauthenticated probe used before pairing.
 *
 * The reply cannot be verified yet -- no key is pinned -- so nothing it says is
 * trusted beyond deciding what to display. The fingerprint it reports is
 * cross-checked against the QR code before any key is enrolled.
 */
export async function fetchServerInfo(
  endpoint: Endpoint,
  timeoutMs = DEFAULT_TIMEOUT_MS,
): Promise<ServerInfo> {
  const response = await fetchWithTimeout(
    `${baseUrl(endpoint)}/v1/server-info`,
    { method: "GET" },
    timeoutMs,
  );
  return parseEnvelope<ServerInfo>(await response.text(), response.status);
}

export async function getStatus(pc: LinkedPC, endpoint: Endpoint): Promise<StatusResponse> {
  return signedCall<StatusResponse>(pc, endpoint, "GET", "/v1/status");
}

export async function unlockSession(
  pc: LinkedPC,
  endpoint: Endpoint,
  sessionId: string | null = null,
): Promise<UnlockResponse> {
  return signedCall<UnlockResponse>(
    pc,
    endpoint,
    "POST",
    "/v1/unlock",
    { session_id: sessionId },
  );
}

export async function lockSession(
  pc: LinkedPC,
  endpoint: Endpoint,
  sessionId: string | null = null,
): Promise<LockResponse> {
  return signedCall<LockResponse>(
    pc,
    endpoint,
    "POST",
    "/v1/lock",
    { session_id: sessionId },
  );
}

export async function relayWake(
  pc: LinkedPC,
  endpoint: Endpoint,
  target: string = "self",
): Promise<WakeResponse> {
  return signedCall<WakeResponse>(pc, endpoint, "POST", "/v1/wake", { target });
}

/**
 * Enroll this device.
 *
 * `expectedFp` comes from the QR code (or from the mDNS TXT record the user
 * selected). The server's self-reported fingerprint is checked against it before
 * the proof is signed, so a machine that is not the one the user chose never
 * receives a signature bound to its identity.
 */
export async function pair(input: {
  endpoint: Endpoint;
  code: string;
  expectedFp: string;
  devicePubkeyB64: string;
  deviceName: string;
  signProof: (message: Uint8Array) => Promise<Uint8Array>;
}): Promise<PairResponse> {
  const info = await fetchServerInfo(input.endpoint);
  if (info.fp !== input.expectedFp) {
    throw new ApiError(
      "bad_server_signature",
      "This PC's identity doesn't match the code you scanned. Do not continue.",
    );
  }

  const code = normalizeCode(input.code);
  const proof = await input.signProof(
    canonicalPair({
      code,
      devicePubkeyB64: input.devicePubkeyB64,
      serverFp: info.fp,
    }),
  );

  const response = await fetchWithTimeout(
    `${baseUrl(input.endpoint)}/v1/pair`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        v: 1,
        code,
        device_pubkey: input.devicePubkeyB64,
        device_name: input.deviceName,
        platform: "ios",
        proof: b64uEncode(proof),
      }),
    },
    PAIR_TIMEOUT_MS,
  );

  const result = parseEnvelope<PairResponse>(await response.text(), response.status);

  // Everything the PC just told us about itself has to agree with what we
  // already believed, or we refuse to pin it.
  if (fingerprint(b64uDecode(result.server_pubkey, 32)) !== result.server_fp) {
    throw new ApiError("bad_server_signature", "the PC's key and fingerprint disagree");
  }
  if (result.server_fp !== input.expectedFp) {
    throw new ApiError("bad_server_signature", "the PC changed identity mid-pairing");
  }

  return result;
}

export type { KeyStorageMode };
