/**
 * The App Group this build was actually signed with.
 *
 * Sideloading tools re-sign with their own team and rewrite identifiers to keep
 * them unique — SideStore appends the team ID, so `com.vercixx.wolunlock`
 * becomes `com.vercixx.wolunlock.QMNZ42…` and the App Group is rewritten to
 * match. Anything that hardcodes `group.com.vercixx.wolunlock` then addresses a
 * container that does not exist, which is silent: `UserDefaults(suiteName:)`
 * returns nil and the keychain simply refuses the access group.
 *
 * The native side reads the real values out of `embedded.mobileprovision`.
 */

import { NativeModule, requireNativeModule } from "expo";
import { Platform } from "react-native";

declare class AppGroupNativeModule extends NativeModule {
  /** Every App Group this bundle is entitled to. Empty if none survived signing. */
  appGroups(): string[];
  /** The one to use for shared storage, including as a keychain access group. */
  sharedAppGroup(): string;
  /** The bundle identifier as installed, which may not be the one in app.json. */
  bundleIdentifier(): string;
  /** Entitlement keys the profile carries. Empty means it was not read. */
  entitlementKeys(): string[];
  /** Whether the bundle contains an `embedded.mobileprovision` at all. */
  hasProvisioningProfile(): boolean;
  /** Write shared state and reload widgets. False if there is no container. */
  publish(json: string): boolean;
}

let cached: AppGroupNativeModule | null | undefined;

function nativeModule(): AppGroupNativeModule | null {
  if (cached !== undefined) return cached;
  if (Platform.OS !== "ios") {
    cached = null;
    return cached;
  }
  try {
    cached = requireNativeModule<AppGroupNativeModule>("AppGroup");
  } catch {
    // Expo Go, or a build without the module linked.
    cached = null;
  }
  return cached;
}

export function isAppGroupAvailable(): boolean {
  return nativeModule() !== null;
}

/**
 * Groups actually granted to this build.
 *
 * An empty list is the signal that shared storage cannot work at all — the
 * entitlement was stripped rather than rewritten.
 */
export function appGroups(): string[] {
  try {
    return nativeModule()?.appGroups() ?? [];
  } catch {
    return [];
  }
}

/** The identifier to use for the shared container and keychain access group. */
export function sharedAppGroup(): string | null {
  try {
    const value = nativeModule()?.sharedAppGroup();
    return value && value.length > 0 ? value : null;
  } catch {
    return null;
  }
}

/**
 * What the signed profile actually granted.
 *
 * Empty while {@link hasProvisioningProfile} is true means the profile exists
 * but could not be parsed; empty with no profile means an unsigned or simulator
 * build.
 */
export function entitlementKeys(): string[] {
  try {
    return nativeModule()?.entitlementKeys() ?? [];
  } catch {
    return [];
  }
}

export function hasProvisioningProfile(): boolean {
  try {
    return nativeModule()?.hasProvisioningProfile() ?? false;
  } catch {
    return false;
  }
}

export function bundleIdentifier(): string | null {
  try {
    return nativeModule()?.bundleIdentifier() ?? null;
  } catch {
    return null;
  }
}

/** Publish shared state for the widget extension. False if it went nowhere. */
export function publishToAppGroup(json: string): boolean {
  try {
    return nativeModule()?.publish(json) ?? false;
  } catch {
    return false;
  }
}
