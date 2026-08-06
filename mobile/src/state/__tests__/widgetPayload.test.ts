/**
 * The payload the widget extension decodes.
 *
 * `targets/widget/SharedState.swift` decodes this with a non-optional `Codable`
 * for everything except `lastIp`, `locked` and `status`, so a missing or
 * misnamed field makes every widget render "Not paired" with no other symptom.
 * These tests pin the contract from the side that can be run.
 */

import { buildWidgetPayload, WIDGET_PAYLOAD_VERSION } from "@/state/widgetPayload";
import type { LinkedPC, PCStatusSnapshot } from "@/state/types";

const PC: LinkedPC = {
  id: "fp-abc",
  name: "Desktop",
  serverFp: "fp-abc",
  serverPubKey: "cHVia2V5",
  hostname: "desktop.local",
  instanceName: "desktop",
  lastIp: "192.0.2.10",
  port: 8765,
  deviceId: "dev-1",
  keyAlias: "alias-1",
  keyMode: "device-only",
  wake: { macs: ["00:11:22:33:44:55"], broadcast: "192.0.2.255", port: 9 },
  capabilities: ["status", "unlock", "wol"],
  pairedAt: 1_700_000_000_000,
  lastSeenAt: null,
};

describe("buildWidgetPayload", () => {
  it("carries every field the Swift decoder requires", () => {
    const payload = buildWidgetPayload([PC], {}, 1_700_000_500_000);

    expect(payload.v).toBe(WIDGET_PAYLOAD_VERSION);
    expect(payload.updatedAt).toBe(1_700_000_500);
    expect(payload.pcs).toHaveLength(1);

    // Named explicitly rather than snapshotted: the point is that renaming one
    // of these breaks this test loudly instead of the widget silently.
    expect(Object.keys(payload.pcs[0]!).sort()).toEqual(
      [
        "broadcast",
        "canUnlock",
        "canLock",
        "deviceId",
        "hostname",
        "id",
        "keyAlias",
        "lastIp",
        "macs",
        "name",
        "port",
        "serverFp",
        "serverPubKey",
        "status",
        "wakePort",
      ].sort(),
    );
  });

  it("flattens the wake block the widget needs", () => {
    const pc = buildWidgetPayload([PC], {}).pcs[0]!;
    expect(pc.macs).toEqual(["00:11:22:33:44:55"]);
    expect(pc.broadcast).toBe("192.0.2.255");
    expect(pc.wakePort).toBe(9);
    expect(pc.canUnlock).toBe(true);
  });

  it("converts timestamps to seconds, which is what Swift reads them as", () => {
    const status: PCStatusSnapshot = {
      reachable: true,
      locked: true,
      sessionId: "c2",
      desktop: "KDE",
      checkedAt: 1_700_000_123_456,
    };
    const pc = buildWidgetPayload([PC], { [PC.id]: status }).pcs[0]!;
    expect(pc.status).toEqual({ reachable: true, locked: true, checkedAt: 1_700_000_123 });
  });

  it("publishes a null status rather than omitting it when nothing is known", () => {
    const pc = buildWidgetPayload([PC], {}).pcs[0]!;
    expect(pc.status).toBeNull();
  });

  it("reports canLock from the capability, independently of canUnlock", () => {
    // The two are separate switches on the service, so one must not imply the
    // other -- a PC with unlock turned off can still be locked.
    const lockOnly = { ...PC, capabilities: ["status", "lock"] };
    const built = buildWidgetPayload([lockOnly], {}).pcs[0]!;
    expect(built.canLock).toBe(true);
    expect(built.canUnlock).toBe(false);
  });

  it("reports canUnlock false for a PC that cannot unlock", () => {
    const limited: LinkedPC = { ...PC, capabilities: ["status", "wol"] };
    expect(buildWidgetPayload([limited], {}).pcs[0]!.canUnlock).toBe(false);
  });

  it("survives a PC with no wake targets", () => {
    const noWake: LinkedPC = { ...PC, wake: { macs: [], broadcast: "", port: 9 } };
    expect(buildWidgetPayload([noWake], {}).pcs[0]!.macs).toEqual([]);
  });
});
