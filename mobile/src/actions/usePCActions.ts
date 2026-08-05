/**
 * The three things a user can do to a PC, with their surrounding bookkeeping:
 * refresh status, wake, unlock.
 *
 * Kept out of the screens so the list and the detail view behave identically.
 */

import { useCallback, useRef, useState } from "react";

import { getStatus, unlockSession } from "@/api/client";
import { resolveAndRemember } from "@/api/endpoint";
import { ApiError } from "@/api/types";
import { sendWakePackets, waitUntilAwake } from "@/actions/wake";
import { confirmBiometrics, migrateToDeviceOnly } from "@/crypto/keys";
import { usePCStore } from "@/state/store";
import type { LinkedPC } from "@/state/types";

export type Busy = null | "status" | "wake" | "unlock";

export type ActionFeedback = {
  tone: "success" | "error" | "info";
  message: string;
} | null;

/** How long a status snapshot is treated as still current. */
export const STATUS_TTL_MS = 15_000;

/**
 * Don't rewrite `lastSeenAt` more often than this.
 *
 * It is bookkeeping, not state anything reacts to, and every write goes through
 * AsyncStorage.
 */
const LAST_SEEN_WRITE_INTERVAL_MS = 60_000;

export function usePCActions(pc: LinkedPC | undefined) {
  const [busy, setBusy] = useState<Busy>(null);
  const [feedback, setFeedback] = useState<ActionFeedback>(null);
  const wakeAbort = useRef<AbortController | null>(null);
  const statusInFlight = useRef<Promise<void> | null>(null);

  const updatePC = usePCStore((state) => state.updatePC);
  const setStatus = usePCStore((state) => state.setStatus);

  const pcId = pc?.id;

  /**
   * The live record, read from the store rather than closed over.
   *
   * This is load-bearing. The store hands back a *new* `LinkedPC` object after
   * every mutation, and these actions mutate it (`lastSeenAt`, `lastIp`,
   * `keyMode`). A callback that captured the object would therefore get a new
   * identity after each successful call -- and since the screens drive polling
   * with `useFocusEffect(refresh)`, whose subscription is keyed on that
   * identity, the effect re-fires, refreshes, mutates, and loops. Left running
   * it polls until the PC's rate limiter answers 429.
   *
   * Depending on `pcId` alone keeps every callback below stable for the life of
   * the row.
   */
  const currentPC = useCallback((): LinkedPC | undefined => {
    if (!pcId) return undefined;
    return usePCStore.getState().pcs.find((item) => item.id === pcId);
  }, [pcId]);

  const remember = useCallback(
    (patch: Partial<LinkedPC>) => {
      if (pcId) updatePC(pcId, patch);
    },
    [pcId, updatePC],
  );

  /** Record that the PC answered, without writing on every single poll. */
  const touchLastSeen = useCallback(
    (target: LinkedPC) => {
      const now = Date.now();
      if (target.lastSeenAt && now - target.lastSeenAt < LAST_SEEN_WRITE_INTERVAL_MS) return;
      updatePC(target.id, { lastSeenAt: now });
    },
    [updatePC],
  );

  /**
   * Move a legacy biometry-protected seed to device-only storage.
   *
   * Records paired before the gate moved prompt for Face ID on every read,
   * which meant a prompt per PC every time the list appeared. This costs one
   * final prompt and then stops, rather than forcing the user to re-pair.
   */
  const ensureMigrated = useCallback(async () => {
    const target = currentPC();
    if (!target || target.keyMode !== "biometric") return;
    if (await migrateToDeviceOnly(target.keyAlias)) {
      updatePC(target.id, { keyMode: "device-only" });
    }
  }, [currentPC, updatePC]);

  const refresh = useCallback((): Promise<void> => {
    const target = currentPC();
    if (!target) return Promise.resolve();

    // Coalesce: a screen regaining focus while a poll is already in flight must
    // join it rather than open a second connection.
    const existing = statusInFlight.current;
    if (existing) return existing;

    const run = (async () => {
      setBusy("status");
      try {
        await ensureMigrated();
        const endpoint = await resolveAndRemember(target, remember);
        const status = await getStatus(target, endpoint);
        setStatus(target.id, {
          reachable: true,
          locked: status.session?.locked ?? null,
          sessionId: status.session?.id ?? null,
          desktop: status.session?.desktop ?? null,
          checkedAt: Date.now(),
        });
        touchLastSeen(target);
      } catch (error) {
        const message = error instanceof ApiError ? error.friendly : String(error);
        setStatus(target.id, {
          reachable: false,
          locked: null,
          sessionId: null,
          desktop: null,
          checkedAt: Date.now(),
          error: message,
        });
      } finally {
        setBusy(null);
        statusInFlight.current = null;
      }
    })();

    statusInFlight.current = run;
    return run;
  }, [currentPC, ensureMigrated, remember, setStatus, touchLastSeen]);

  /**
   * Refresh only if what is on screen has gone stale.
   *
   * Bouncing between the list and a detail screen fires a focus effect each
   * way; without this the same answer is fetched three times in five seconds.
   * Takes no arguments deliberately, so it is safe to hand straight to `onPress`.
   */
  const refreshIfStale = useCallback((): void => {
    if (!pcId) return;
    const snapshot = usePCStore.getState().statuses[pcId];
    if (snapshot && Date.now() - snapshot.checkedAt < STATUS_TTL_MS) return;
    void refresh();
  }, [pcId, refresh]);

  const wake = useCallback(async () => {
    const target = currentPC();
    if (!target) return;
    setBusy("wake");
    setFeedback(null);
    wakeAbort.current?.abort();
    const controller = new AbortController();
    wakeAbort.current = controller;

    try {
      const result = await sendWakePackets(target);
      if (result.packetsSent === 0) {
        setFeedback({ tone: "error", message: result.error ?? "Could not send a magic packet." });
        return;
      }

      setFeedback({
        tone: "info",
        message:
          `Sent ${result.packetsSent} magic packet${result.packetsSent === 1 ? "" : "s"}. ` +
          `Waiting for ${target.name}…` +
          (result.broadcastBlocked ? " (iOS blocked broadcast; used its last known IP.)" : ""),
      });

      // Confirm rather than assume: poll until the PC actually answers.
      const awake = await waitUntilAwake(target, { signal: controller.signal });
      if (controller.signal.aborted) return;

      if (awake) {
        setFeedback({ tone: "success", message: `${target.name} is awake.` });
        await refresh();
      } else {
        setFeedback({
          tone: "error",
          message: result.broadcastBlocked
            ? `${target.name} didn't come online. Only a unicast packet could be sent, which ` +
              `needs your router to still hold an ARP entry for ${target.lastIp ?? "its IP"}. ` +
              `A DHCP reservation plus a static ARP entry makes that reliable.`
            : `${target.name} didn't come online. The packet was sent, so check Wake-on-LAN ` +
              `is enabled in its BIOS and NIC.`,
        });
      }
    } catch (error) {
      setFeedback({
        tone: "error",
        message: error instanceof ApiError ? error.friendly : String(error),
      });
    } finally {
      setBusy(null);
    }
  }, [currentPC, refresh]);

  const unlock = useCallback(async () => {
    const target = currentPC();
    if (!target) return;
    setBusy("unlock");
    setFeedback(null);
    try {
      await ensureMigrated();

      // The one place biometrics are asked for. Unlocking a PC is the action
      // worth confirming; checking whether it is online is not.
      if (target.requireBiometricsForUnlock !== false) {
        if (!(await confirmBiometrics(`Unlock ${target.name}`))) {
          setFeedback({ tone: "error", message: "Cancelled." });
          return;
        }
      }

      const endpoint = await resolveAndRemember(target, remember);
      const result = await unlockSession(target, endpoint);
      setFeedback({
        tone: "success",
        message: result.was_locked
          ? `Unlocked session ${result.session_id}.`
          : `${target.name} was already unlocked.`,
      });
      setStatus(target.id, {
        reachable: true,
        locked: false,
        sessionId: result.session_id,
        desktop: result.desktop,
        checkedAt: Date.now(),
      });
      touchLastSeen(target);
    } catch (error) {
      setFeedback({
        tone: "error",
        message: error instanceof ApiError ? error.friendly : String(error),
      });
    } finally {
      setBusy(null);
    }
  }, [currentPC, ensureMigrated, remember, setStatus, touchLastSeen]);

  const cancelWake = useCallback(() => {
    wakeAbort.current?.abort();
    setBusy(null);
  }, []);

  return { busy, feedback, setFeedback, refresh, refreshIfStale, wake, unlock, cancelWake };
}
