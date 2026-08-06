/**
 * Regression tests for the status-poll loop.
 *
 * The screens poll with `useFocusEffect(() => refreshIfStale())`, whose effect
 * is re-subscribed whenever the callback's identity changes. `refresh` used to
 * close over the `LinkedPC` object, and a successful poll writes back to that
 * record -- so the store produced a new object, the callback got a new identity,
 * the effect re-fired, and the phone hammered the PC until its rate limiter
 * started answering 429. These tests pin the invariant that broke it.
 */

import { act, create } from "react-test-renderer";
import { useEffect } from "react";

import { usePCActions } from "@/actions/usePCActions";
import { usePCStore } from "@/state/store";
import type { LinkedPC } from "@/state/types";

jest.mock("@react-native-async-storage/async-storage", () =>
  require("@react-native-async-storage/async-storage/jest/async-storage-mock"),
);

jest.mock("@/crypto/keys", () => ({
  migrateToDeviceOnly: jest.fn(async () => false),
  confirmBiometrics: jest.fn(async () => true),
  deleteDeviceKey: jest.fn(async () => undefined),
}));

jest.mock("@/api/endpoint", () => ({
  resolveAndRemember: jest.fn(async () => ({ host: "pc.local", port: 8765 })),
}));

jest.mock("@/api/client", () => ({
  getStatus: jest.fn(async () => ({
    session: { id: "c2", locked: true, desktop: "KDE" },
  })),
  unlockSession: jest.fn(),
  lockSession: jest.fn(async () => ({
    session_id: "c2",
    was_locked: false,
    locked: true,
    type: "wayland",
    desktop: "KDE",
    seat: "seat0",
  })),
}));

jest.mock("@/actions/wake", () => ({
  sendWakePackets: jest.fn(),
  waitUntilAwake: jest.fn(),
}));

import { getStatus, lockSession } from "@/api/client";
import { confirmBiometrics } from "@/crypto/keys";

const PC: LinkedPC = {
  id: "fp-abc",
  name: "Desktop",
  serverFp: "fp-abc",
  serverPubKey: "pub",
  hostname: "pc.local",
  instanceName: "pc",
  lastIp: null,
  port: 8765,
  deviceId: "dev-1",
  keyAlias: "alias-1",
  keyMode: "device-only",
  wake: { macs: ["00:11:22:33:44:55"], broadcast: "255.255.255.255", port: 9 },
  capabilities: ["unlock", "lock", "wake"],
  pairedAt: 0,
  lastSeenAt: null,
};

/** Mirrors how the list screen drives the hook. */
function Row() {
  const pc = usePCStore((state) => state.pcs[0]);
  const { refresh } = usePCActions(pc);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  return null;
}

async function settle() {
  // Several turns: resolve endpoint -> status -> store writes -> re-render.
  for (let i = 0; i < 10; i += 1) {
    await act(async () => {
      await Promise.resolve();
    });
  }
}

beforeEach(() => {
  jest.clearAllMocks();
  usePCStore.setState({ pcs: [PC], statuses: {}, hydrated: true });
});

describe("usePCActions", () => {
  it("polls once when mounted, despite writing back to the PC record", async () => {
    let tree!: ReturnType<typeof create>;
    act(() => {
      tree = create(<Row />);
    });
    await settle();
    expect(getStatus).toHaveBeenCalledTimes(1);
    act(() => tree.unmount());
  });

  it("does not re-poll when an unrelated store write replaces the record", async () => {
    let tree!: ReturnType<typeof create>;
    act(() => {
      tree = create(<Row />);
    });
    await settle();
    expect(getStatus).toHaveBeenCalledTimes(1);

    // What `resolveAndRemember` does after a DHCP change: a real mutation,
    // producing a genuinely new `LinkedPC` object.
    act(() => {
      usePCStore.getState().updatePC(PC.id, { lastIp: "192.0.2.10" });
    });
    await settle();

    expect(usePCStore.getState().pcs[0]?.lastIp).toBe("192.0.2.10");
    expect(getStatus).toHaveBeenCalledTimes(1);
    act(() => tree.unmount());
  });

  it("coalesces overlapping refreshes into one request", async () => {
    let actions: ReturnType<typeof usePCActions> | undefined;
    function Probe() {
      actions = usePCActions(usePCStore((state) => state.pcs[0]));
      return null;
    }
    let tree!: ReturnType<typeof create>;
    act(() => {
      tree = create(<Probe />);
    });

    await act(async () => {
      await Promise.all([actions!.refresh(), actions!.refresh(), actions!.refresh()]);
    });
    await settle();

    expect(getStatus).toHaveBeenCalledTimes(1);
    act(() => tree.unmount());
  });

  it("refreshIfStale skips a snapshot that is still current", async () => {
    let actions: ReturnType<typeof usePCActions> | undefined;
    function Probe() {
      actions = usePCActions(usePCStore((state) => state.pcs[0]));
      return null;
    }
    let tree!: ReturnType<typeof create>;
    act(() => {
      tree = create(<Probe />);
    });

    await act(async () => {
      actions!.refreshIfStale();
    });
    await settle();
    expect(getStatus).toHaveBeenCalledTimes(1);

    await act(async () => {
      actions!.refreshIfStale();
    });
    await settle();
    expect(getStatus).toHaveBeenCalledTimes(1);

    // Age the snapshot past the freshness window.
    act(() => {
      const status = usePCStore.getState().statuses[PC.id]!;
      usePCStore
        .getState()
        .setStatus(PC.id, { ...status, checkedAt: Date.now() - 60_000 });
    });
    await act(async () => {
      actions!.refreshIfStale();
    });
    await settle();
    expect(getStatus).toHaveBeenCalledTimes(2);

    act(() => tree.unmount());
  });
});

describe("updatePC", () => {
  it("leaves the record untouched when the patch changes nothing", () => {
    const before = usePCStore.getState().pcs[0];
    usePCStore.getState().updatePC(PC.id, { lastIp: null, port: 8765 });
    expect(usePCStore.getState().pcs[0]).toBe(before);
  });

  it("replaces the record when the patch changes something", () => {
    const before = usePCStore.getState().pcs[0];
    usePCStore.getState().updatePC(PC.id, { lastIp: "192.0.2.10" });
    expect(usePCStore.getState().pcs[0]).not.toBe(before);
    expect(usePCStore.getState().pcs[0]?.lastIp).toBe("192.0.2.10");
  });

  it("ignores a patch for an id that isn't paired", () => {
    const before = usePCStore.getState().pcs;
    usePCStore.getState().updatePC("nope", { lastIp: "192.0.2.10" });
    expect(usePCStore.getState().pcs).toBe(before);
  });
});

describe("lock", () => {
  it("locks without asking for biometrics", async () => {
    // The asymmetry that matters: unlock hands whoever holds the phone a live
    // desktop and is gated; lock costs its owner a password prompt and is not.
    let actions: ReturnType<typeof usePCActions> | undefined;
    function Probe() {
      actions = usePCActions(usePCStore((state) => state.pcs[0]));
      return null;
    }
    let tree!: ReturnType<typeof create>;
    act(() => {
      tree = create(<Probe />);
    });

    await act(async () => {
      await actions!.lock();
    });
    await settle();

    expect(lockSession).toHaveBeenCalledTimes(1);
    expect(confirmBiometrics).not.toHaveBeenCalled();
    expect(usePCStore.getState().statuses[PC.id]?.locked).toBe(true);
    act(() => tree.unmount());
  });
});
