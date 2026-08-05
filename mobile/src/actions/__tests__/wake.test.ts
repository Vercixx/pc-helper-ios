/**
 * Wake destination ordering.
 *
 * The ordering is load-bearing: on a build signed with a free Apple ID, iOS
 * refuses UDP broadcast, so the unicast attempt is the only one that can work.
 */

import { wakeDestinations } from "../wake";
import type { LinkedPC } from "@/state/types";

function makePC(overrides: Partial<LinkedPC> = {}): LinkedPC {
  return {
    id: "fp",
    name: "Test PC",
    serverFp: "fp",
    serverPubKey: "pk",
    hostname: "test-pc.local",
    instanceName: "test-pc",
    lastIp: "192.168.1.50",
    port: 8765,
    deviceId: "device",
    keyAlias: "alias",
    keyMode: "biometric",
    wake: { macs: ["00:00:5e:00:53:01"], broadcast: "192.168.1.255", port: 9 },
    capabilities: ["wol", "unlock", "status"],
    pairedAt: 0,
    lastSeenAt: null,
    ...overrides,
  };
}

describe("wakeDestinations", () => {
  it("puts unicast first, because broadcast needs an entitlement", () => {
    const destinations = wakeDestinations(makePC(), ["192.168.1.255"]);
    expect(destinations[0]).toEqual({ address: "192.168.1.50", kind: "unicast" });
    expect(destinations.some((d) => d.kind === "broadcast")).toBe(true);
  });

  it("still offers broadcast when no IP has been recorded yet", () => {
    const destinations = wakeDestinations(makePC({ lastIp: null }), []);
    expect(destinations).toEqual([{ address: "192.168.1.255", kind: "broadcast" }]);
  });

  it("adds the phone's own subnet broadcast for when it has moved networks", () => {
    const destinations = wakeDestinations(makePC({ lastIp: null }), ["10.0.0.255"]);
    expect(destinations.map((d) => d.address)).toEqual(["192.168.1.255", "10.0.0.255"]);
  });

  it("de-duplicates addresses", () => {
    const destinations = wakeDestinations(makePC({ lastIp: null }), [
      "192.168.1.255",
      "192.168.1.255",
    ]);
    expect(destinations).toHaveLength(1);
  });

  it("drops anything that is not a literal IPv4 address", () => {
    // sendMagicPacket goes through inet_pton, so a hostname would just throw.
    const destinations = wakeDestinations(
      makePC({ lastIp: "test-pc.local" as unknown as string }),
      ["not-an-ip", ""],
    );
    expect(destinations.every((d) => /^\d+\.\d+\.\d+\.\d+$/.test(d.address))).toBe(true);
    expect(destinations.some((d) => d.address === "test-pc.local")).toBe(false);
  });

  it("returns nothing when there is no usable address at all", () => {
    const pc = makePC({ lastIp: null, wake: { macs: ["aa"], broadcast: "", port: 9 } });
    expect(wakeDestinations(pc, [])).toEqual([]);
  });
});
