/**
 * Device key material.
 *
 * One Ed25519 keypair per paired PC, so revoking one machine's trust cannot
 * affect another. The 32-byte seed lives in the iOS keychain via
 * `expo-secure-store`; only that seed is secret, and it never appears in the
 * zustand store, in AsyncStorage, or in any log.
 *
 * An Ed25519 private key *is* 32 uniformly random bytes, so the seed comes
 * straight from `expo-crypto`'s CSPRNG with no RNG polyfill involved.
 */

import * as ed from "@noble/ed25519";
import { sha512 } from "@noble/hashes/sha2.js";
import * as Crypto from "expo-crypto";
import * as SecureStore from "expo-secure-store";

import {
  PUBKEY_BYTES,
  SEED_BYTES,
  b64uDecode,
  b64uEncode,
  deviceIdFor,
  fingerprint,
} from "./canonical";

// @noble/ed25519 v3 ships without a SHA-512 implementation so it can stay
// dependency-free. Both hooks are wired to the pure-JS implementation rather
// than WebCrypto, which React Native does not provide.
ed.hashes.sha512 = sha512;
ed.hashes.sha512Async = async (message: Uint8Array) => sha512(message);

const KEY_PREFIX = "wolunlock.seed.";

export type KeyStorageMode = "biometric" | "device-only";

export type DeviceKey = {
  publicKey: Uint8Array;
  publicKeyB64: string;
  deviceId: string;
  fingerprint: string;
};

function storageKey(alias: string): string {
  return `${KEY_PREFIX}${alias}`;
}

function optionsFor(mode: KeyStorageMode, prompt: string): SecureStore.SecureStoreOptions {
  return {
    keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
    requireAuthentication: mode === "biometric",
    authenticationPrompt: prompt,
  };
}

/**
 * Whether the keychain can hold a biometry-protected item on this device.
 *
 * False when no passcode or biometric is enrolled. Storing with
 * `requireAuthentication` would then fail at write time, so this is checked up
 * front and the caller falls back to device-only protection.
 */
export async function canUseBiometricStorage(): Promise<boolean> {
  try {
    return await SecureStore.canUseBiometricAuthentication();
  } catch {
    return false;
  }
}

/**
 * Generate a keypair and persist the seed.
 *
 * Returns the public half plus the storage mode actually achieved, which the
 * caller records on the PC so the UI can tell the user whether Face ID guards
 * the unlock action.
 */
export async function createDeviceKey(
  alias: string,
  preferred: KeyStorageMode = "biometric",
): Promise<DeviceKey & { mode: KeyStorageMode }> {
  const seed = Crypto.getRandomBytes(SEED_BYTES);
  if (seed.length !== SEED_BYTES) {
    throw new Error("the platform CSPRNG returned the wrong number of bytes");
  }

  const publicKey = ed.getPublicKey(seed);
  if (publicKey.length !== PUBKEY_BYTES) {
    throw new Error("derived public key has the wrong length");
  }

  let mode: KeyStorageMode = preferred;
  if (mode === "biometric" && !(await canUseBiometricStorage())) {
    mode = "device-only";
  }

  const value = b64uEncode(seed);
  try {
    await SecureStore.setItemAsync(
      storageKey(alias),
      value,
      optionsFor(mode, "Protect the key that unlocks your PC"),
    );
  } catch (error) {
    if (mode !== "biometric") throw error;
    // Biometric enrollment can change between the check above and the write.
    mode = "device-only";
    await SecureStore.setItemAsync(storageKey(alias), value, optionsFor(mode, ""));
  }

  seed.fill(0);

  return {
    publicKey,
    publicKeyB64: b64uEncode(publicKey),
    deviceId: deviceIdFor(publicKey),
    fingerprint: fingerprint(publicKey),
    mode,
  };
}

/**
 * Sign a message with a stored key.
 *
 * When the key was stored with biometric protection, reading it triggers the
 * Face ID prompt -- which is exactly the gate we want in front of unlocking a
 * PC, and the reason the seed is fetched per signature rather than cached.
 */
export async function signWithDeviceKey(
  alias: string,
  message: Uint8Array,
  mode: KeyStorageMode,
  prompt = "Unlock your PC",
): Promise<Uint8Array> {
  const stored = await SecureStore.getItemAsync(storageKey(alias), optionsFor(mode, prompt));
  if (!stored) {
    throw new Error(
      "This device's key is missing from the keychain. Pair with the PC again.",
    );
  }

  const seed = b64uDecode(stored, SEED_BYTES);
  try {
    return ed.sign(message, seed);
  } finally {
    seed.fill(0);
  }
}

export async function getPublicKey(
  alias: string,
  mode: KeyStorageMode,
  prompt = "Confirm it's you",
): Promise<Uint8Array> {
  const stored = await SecureStore.getItemAsync(storageKey(alias), optionsFor(mode, prompt));
  if (!stored) throw new Error("key not found");
  const seed = b64uDecode(stored, SEED_BYTES);
  try {
    return ed.getPublicKey(seed);
  } finally {
    seed.fill(0);
  }
}

export async function deleteDeviceKey(alias: string): Promise<void> {
  // No options: deletion must succeed even if biometry is unavailable, or a
  // revoked PC would leave its key stranded in the keychain forever.
  try {
    await SecureStore.deleteItemAsync(storageKey(alias));
  } catch {
    /* already gone */
  }
}

/** A fresh key alias. Random rather than derived, so re-pairing the same PC
 * never collides with a key that is still being deleted. */
export function newKeyAlias(): string {
  return b64uEncode(Crypto.getRandomBytes(12));
}

export { ed };
