/**
 * What the app publishes into the App Group for the widget extension.
 *
 * The consumer is `targets/widget/SharedState.swift`; the two shapes must agree
 * field for field. Kept separate from `widgetBridge.ts` so it carries no native
 * imports and can be tested directly.
 *
 * Nothing secret is included. Every field here is already in AsyncStorage
 * unencrypted -- addresses, public identities, last known lock state. The
 * Ed25519 seed stays in the keychain and is reached separately, by alias.
 */

import type { LinkedPC, PCStatusSnapshot } from "./types";

/**
 * Bumped to 2 when `canLock` was added.
 *
 * The version gate is what makes adding a field safe. A state file written by
 * an older build has no `canLock`, and `PC` decodes it as a non-optional Bool,
 * so the whole payload would be rejected anyway -- but by an incidental
 * `try?` rather than on purpose. Bumping says it out loud: the readers see a
 * version they do not know, report "no PC is paired", and the app rewrites the
 * file the next time it runs.
 */
export const WIDGET_PAYLOAD_VERSION = 2;

export type WidgetSnapshot = {
  reachable: boolean;
  locked: boolean | null;
  /** Unix **seconds** -- Swift's `Date(timeIntervalSince1970:)` takes seconds. */
  checkedAt: number;
};

export type WidgetPC = {
  id: string;
  name: string;
  hostname: string;
  port: number;
  lastIp: string | null;
  deviceId: string;
  keyAlias: string;
  serverFp: string;
  serverPubKey: string;
  macs: string[];
  broadcast: string;
  wakePort: number;
  canUnlock: boolean;
  canLock: boolean;
  status: WidgetSnapshot | null;
};

export type WidgetPayload = {
  v: number;
  pcs: WidgetPC[];
  updatedAt: number;
};

function toSeconds(milliseconds: number): number {
  return Math.floor(milliseconds / 1000);
}

export function buildWidgetPayload(
  pcs: LinkedPC[],
  statuses: Record<string, PCStatusSnapshot>,
  now: number = Date.now(),
): WidgetPayload {
  return {
    v: WIDGET_PAYLOAD_VERSION,
    updatedAt: toSeconds(now),
    pcs: pcs.map((pc) => {
      const status = statuses[pc.id];
      return {
        id: pc.id,
        name: pc.name,
        hostname: pc.hostname,
        port: pc.port,
        lastIp: pc.lastIp,
        deviceId: pc.deviceId,
        keyAlias: pc.keyAlias,
        serverFp: pc.serverFp,
        serverPubKey: pc.serverPubKey,
        macs: pc.wake.macs,
        broadcast: pc.wake.broadcast,
        wakePort: pc.wake.port,
        canUnlock: pc.capabilities.includes("unlock"),
        canLock: pc.capabilities.includes("lock"),
        status: status
          ? {
              reachable: status.reachable,
              locked: status.locked,
              checkedAt: toSeconds(status.checkedAt),
            }
          : null,
      };
    }),
  };
}
