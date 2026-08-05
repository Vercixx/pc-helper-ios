import type { KeyStorageMode } from "@/crypto/keys";

/**
 * A paired PC as persisted on the phone.
 *
 * Deliberately contains no secret: the Ed25519 seed lives in the keychain under
 * `keyAlias`, so this record can sit in AsyncStorage without risk.
 */
export type LinkedPC = {
  /** Stable local id -- the server fingerprint, which cannot collide. */
  id: string;
  /** Display name, editable by the user. */
  name: string;

  /** Pinned server identity. Everything is verified against these two. */
  serverFp: string;
  serverPubKey: string;

  /** mDNS hostname, e.g. "my-pc.local". Survives DHCP changes. */
  hostname: string;
  /** Bonjour instance name, for re-resolving via mDNS. */
  instanceName: string;
  /** Last address that actually worked, tried in parallel with the hostname. */
  lastIp: string | null;
  port: number;

  /** Our identity on this PC, as issued by it. */
  deviceId: string;
  /** Keychain alias for our private seed. */
  keyAlias: string;
  keyMode: KeyStorageMode;

  wake: { macs: string[]; broadcast: string; port: number };
  capabilities: string[];

  pairedAt: number;
  lastSeenAt: number | null;
};

export type PCStatusSnapshot = {
  reachable: boolean;
  locked: boolean | null;
  sessionId: string | null;
  desktop: string | null;
  checkedAt: number;
  error?: string;
};
