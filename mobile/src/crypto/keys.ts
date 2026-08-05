/**
 * Device key material.
 *
 * One Ed25519 keypair per paired PC, so revoking one machine's trust cannot
 * affect another. The 32-byte seed lives in the iOS keychain via
 * `expo-secure-store`; only that seed is secret, and it never appears in the
 * zustand store, in AsyncStorage, or in any log.
 *
 * Where the biometric gate lives
 * ------------------------------
 * The seed is stored *without* `requireAuthentication`, protected by
 * `WHEN_UNLOCKED_THIS_DEVICE_ONLY` — readable only while the phone itself is
 * unlocked, and never restorable to another device.
 *
 * Keychain-level biometry was the original design and was wrong in practice:
 * every signed request reads the seed, including the background status poll on
 * the PC list, so simply looking at the list produced a Face ID prompt per PC
 * per visit. The gate now sits on the *action* instead
 * (:func:`confirmBiometrics`, called before unlocking), which prompts exactly
 * once when it means something.
 *
 * An Ed25519 private key is 32 uniformly random bytes, so the seed comes
 * straight from `expo-crypto`'s CSPRNG with no RNG polyfill involved.
 */

import * as ed from "@noble/ed25519";
import { sha512 } from "@noble/hashes/sha2.js";
import * as Crypto from "expo-crypto";
import * as LocalAuthentication from "expo-local-authentication";
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

/**
 * Keychain access group shared with the widget extension.
 *
 * An App Group identifier is a legal keychain access group, and it is the right
 * one to use here: unlike `$(AppIdentifierPrefix)com.vercixx.wolunlock` it is a
 * literal the extension can name at compile time without knowing the team
 * prefix it was signed with.
 *
 * Every write falls back to the app-private default if this is refused, which is
 * what happens when the entitlement did not survive signing. The app then works
 * exactly as before and only the widget's live status is lost.
 */
const SHARED_ACCESS_GROUP = "group.com.vercixx.wolunlock";

/**
 * How a seed is stored in the keychain.
 *
 * `"device-only"` is what everything uses now. `"biometric"` only appears on
 * records paired before the gate moved, and is migrated away on first use by
 * {@link migrateToDeviceOnly}.
 */
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

function optionsFor(
  mode: KeyStorageMode,
  prompt: string,
  accessGroup?: string,
): SecureStore.SecureStoreOptions {
  return {
    keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
    requireAuthentication: mode === "biometric",
    authenticationPrompt: prompt,
    ...(accessGroup ? { accessGroup } : {}),
  };
}

/**
 * Store a seed in the shared group, falling back to the app-private default.
 *
 * Returns which group the item ended up in, for callers that want to know
 * whether the widget will be able to read it.
 */
async function writeSeed(
  alias: string,
  encodedSeed: string,
  mode: KeyStorageMode,
): Promise<"shared" | "private"> {
  try {
    await SecureStore.setItemAsync(
      storageKey(alias),
      encodedSeed,
      optionsFor(mode, "", SHARED_ACCESS_GROUP),
    );
    return "shared";
  } catch {
    await SecureStore.setItemAsync(storageKey(alias), encodedSeed, optionsFor(mode, ""));
    return "private";
  }
}

/**
 * Read a seed from wherever it is.
 *
 * Checks the shared group first, then the app-private default, and promotes a
 * private item to the shared group when it finds one -- so a PC paired before
 * the widget existed becomes visible to it without re-pairing.
 */
async function readSeed(
  alias: string,
  mode: KeyStorageMode,
  prompt: string,
): Promise<string | null> {
  try {
    const shared = await SecureStore.getItemAsync(
      storageKey(alias),
      optionsFor(mode, prompt, SHARED_ACCESS_GROUP),
    );
    if (shared) return shared;
  } catch {
    /* No entitlement for the shared group. Fall through to the private one. */
  }

  const priv = await SecureStore.getItemAsync(storageKey(alias), optionsFor(mode, prompt));
  if (!priv) return null;

  try {
    await SecureStore.setItemAsync(
      storageKey(alias),
      priv,
      optionsFor("device-only", "", SHARED_ACCESS_GROUP),
    );
  } catch {
    /* Promotion is best-effort; the seed is still usable where it is. */
  }
  return priv;
}

/** Generate a keypair and persist the seed. */
export async function createDeviceKey(alias: string): Promise<DeviceKey> {
  const seed = Crypto.getRandomBytes(SEED_BYTES);
  if (seed.length !== SEED_BYTES) {
    throw new Error("the platform CSPRNG returned the wrong number of bytes");
  }

  const publicKey = ed.getPublicKey(seed);
  if (publicKey.length !== PUBKEY_BYTES) {
    throw new Error("derived public key has the wrong length");
  }

  await writeSeed(alias, b64uEncode(seed), "device-only");
  seed.fill(0);

  return {
    publicKey,
    publicKeyB64: b64uEncode(publicKey),
    deviceId: deviceIdFor(publicKey),
    fingerprint: fingerprint(publicKey),
  };
}

/** Sign a message. Never prompts: the biometric gate is on the action. */
export async function signWithDeviceKey(
  alias: string,
  message: Uint8Array,
  mode: KeyStorageMode = "device-only",
): Promise<Uint8Array> {
  const stored = await readSeed(alias, mode, "Confirm it's you");
  if (!stored) {
    throw new Error("This device's key is missing from the keychain. Pair with the PC again.");
  }

  const seed = b64uDecode(stored, SEED_BYTES);
  try {
    return ed.sign(message, seed);
  } finally {
    seed.fill(0);
  }
}

/**
 * Rewrite a legacy biometry-protected seed as device-only.
 *
 * Costs one Face ID prompt — the last one that record will ever cause — and
 * saves the user from having to re-pair. Returns false if the read failed, in
 * which case the caller should leave the stored mode alone and try again later.
 */
export async function migrateToDeviceOnly(alias: string): Promise<boolean> {
  try {
    const stored = await readSeed(alias, "biometric", "Update how this key is stored");
    if (!stored) return false;
    await writeSeed(alias, stored, "device-only");
    return true;
  } catch {
    return false;
  }
}

/**
 * Ask for Face ID / Touch ID / passcode before a sensitive action.
 *
 * Returns true when the device has no biometric hardware or nothing enrolled:
 * refusing outright would make the app unusable on such a device, and the
 * seed is already gated behind the phone's own lock screen.
 */
export async function confirmBiometrics(reason: string): Promise<boolean> {
  try {
    if (!(await LocalAuthentication.hasHardwareAsync())) return true;
    if (!(await LocalAuthentication.isEnrolledAsync())) return true;

    const result = await LocalAuthentication.authenticateAsync({
      promptMessage: reason,
      // Let the device passcode stand in when a face is not recognised.
      disableDeviceFallback: false,
      cancelLabel: "Cancel",
    });
    return result.success;
  } catch {
    return false;
  }
}

export async function deleteDeviceKey(alias: string): Promise<void> {
  // Both groups: a seed promoted to the shared group may have left the
  // app-private copy behind, and unpairing must not leave a usable key anywhere.
  for (const options of [
    optionsFor("device-only", "", SHARED_ACCESS_GROUP),
    optionsFor("device-only", ""),
  ]) {
    try {
      await SecureStore.deleteItemAsync(storageKey(alias), options);
    } catch {
      /* already gone, or no entitlement for that group */
    }
  }
}

/**
 * A fresh key alias. Random rather than derived, so re-pairing the same PC
 * never collides with a key that is still being deleted.
 */
export function newKeyAlias(): string {
  return b64uEncode(Crypto.getRandomBytes(12));
}

export { ed };
