/**
 * Enrolling this phone with a PC.
 *
 * Order matters: generate a key, confirm the PC's identity matches the code the
 * user scanned, sign a proof bound to that identity and that code, and only then
 * persist anything. If any step fails the keychain item is removed, so a failed
 * attempt leaves nothing behind.
 */

import * as Device from "expo-device";

import { pair as pairApi, type Endpoint } from "@/api/client";
import { normalizeCode } from "@/crypto/canonical";
import { createDeviceKey, deleteDeviceKey, newKeyAlias, signWithDeviceKey } from "@/crypto/keys";
import { usePCStore } from "@/state/store";
import type { LinkedPC } from "@/state/types";

/** Everything the pairing QR code carries (PROTOCOL.md 8.1). */
export type PairingTicket = {
  name: string;
  host: string;
  port: number;
  fingerprint: string;
  code: string | null;
  macs: string[];
  broadcast: string | null;
};

/**
 * Parse a `wolunlock:1?...` QR payload.
 *
 * Returns null rather than throwing: the camera will happily scan unrelated
 * codes, and that is not an error worth surfacing.
 */
export function parsePairingTicket(raw: string): PairingTicket | null {
  const trimmed = raw.trim();
  const match = /^wolunlock:(\d+)\?(.*)$/i.exec(trimmed);
  if (!match) return null;
  if (match[1] !== "1") return null;

  const params = new Map<string, string>();
  for (const pair of (match[2] ?? "").split("&")) {
    if (!pair) continue;
    const index = pair.indexOf("=");
    if (index === -1) continue;
    const key = pair.slice(0, index);
    const value = pair.slice(index + 1);
    try {
      params.set(key, decodeURIComponent(value.replace(/\+/g, " ")));
    } catch {
      return null;
    }
  }

  const host = params.get("h");
  const fingerprint = params.get("f");
  if (!host || !fingerprint) return null;

  const port = Number.parseInt(params.get("p") ?? "8765", 10);
  if (!Number.isInteger(port) || port < 1 || port > 65535) return null;

  const macs = (params.get("m") ?? "")
    .split(",")
    .filter(Boolean)
    .map((hex) => hex.replace(/[^0-9a-fA-F]/g, ""))
    .filter((hex) => hex.length === 12)
    .map((hex) => (hex.match(/.{2}/g) ?? []).join(":").toLowerCase());

  return {
    name: params.get("n") || host.replace(/\.local$/, ""),
    host,
    port,
    fingerprint,
    code: params.get("c") ? normalizeCode(params.get("c")!) : null,
    macs,
    broadcast: params.get("b") ?? null,
  };
}

function phoneName(): string {
  const name = Device.deviceName?.trim();
  if (name) return name.slice(0, 60);
  const model = Device.modelName?.trim();
  return model ? `${model}` : "iPhone";
}

export type PairOutcome = { pc: LinkedPC };

/**
 * Run the full enrollment.
 *
 * Blocks for as long as the operator takes to approve at the PC (the service
 * parks the request for up to 60 seconds), so callers should show a "waiting for
 * approval" state.
 */
export async function pairWithPC(input: {
  endpoint: Endpoint;
  code: string;
  expectedFingerprint: string;
  instanceName?: string;
  fallbackName?: string;
}): Promise<PairOutcome> {
  const alias = newKeyAlias();
  const key = await createDeviceKey(alias);

  try {
    const result = await pairApi({
      endpoint: input.endpoint,
      code: input.code,
      expectedFp: input.expectedFingerprint,
      devicePubkeyB64: key.publicKeyB64,
      deviceName: phoneName(),
      // Signing the proof reads the seed back out of the keychain, which is
      // also a live check that we can use the key we just created.
      signProof: (message) => signWithDeviceKey(alias, message),
    });

    if (result.device_id !== key.deviceId) {
      throw new Error("the PC issued a device id we did not derive; refusing to pair");
    }

    const hostname = input.endpoint.host.endsWith(".local")
      ? input.endpoint.host
      : `${input.instanceName ?? result.name}.local`;

    const pc: LinkedPC = {
      // The server fingerprint is globally unique and stable, which makes it the
      // natural primary key: re-pairing updates the row instead of duplicating.
      id: result.server_fp,
      name: result.name || input.fallbackName || "PC",
      serverFp: result.server_fp,
      serverPubKey: result.server_pubkey,
      hostname,
      instanceName: input.instanceName ?? hostname.replace(/\.local$/, ""),
      lastIp: /^\d{1,3}(\.\d{1,3}){3}$/.test(input.endpoint.host) ? input.endpoint.host : null,
      port: input.endpoint.port,
      deviceId: result.device_id,
      keyAlias: alias,
      keyMode: "device-only",
      requireBiometricsForUnlock: true,
      wake: {
        macs: result.wake?.macs ?? [],
        broadcast: result.wake?.broadcast ?? "255.255.255.255",
        port: result.wake?.port ?? 9,
      },
      capabilities: result.caps ?? [],
      pairedAt: Date.now(),
      lastSeenAt: Date.now(),
    };

    usePCStore.getState().addOrReplacePC(pc);
    return { pc };
  } catch (error) {
    // Never leave an orphaned key in the keychain for a pairing that failed.
    await deleteDeviceKey(alias);
    throw error;
  }
}
