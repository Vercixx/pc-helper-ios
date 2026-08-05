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
import { usePCStore } from "@/state/store";
import type { LinkedPC } from "@/state/types";

export type Busy = null | "status" | "wake" | "unlock";

export type ActionFeedback = {
  tone: "success" | "error" | "info";
  message: string;
} | null;

export function usePCActions(pc: LinkedPC | undefined) {
  const [busy, setBusy] = useState<Busy>(null);
  const [feedback, setFeedback] = useState<ActionFeedback>(null);
  const wakeAbort = useRef<AbortController | null>(null);

  const updatePC = usePCStore((state) => state.updatePC);
  const setStatus = usePCStore((state) => state.setStatus);

  const remember = useCallback(
    (patch: Partial<LinkedPC>) => {
      if (pc) updatePC(pc.id, patch);
    },
    [pc, updatePC],
  );

  const refresh = useCallback(async () => {
    if (!pc) return;
    setBusy("status");
    try {
      const endpoint = await resolveAndRemember(pc, remember);
      const status = await getStatus(pc, endpoint);
      setStatus(pc.id, {
        reachable: true,
        locked: status.session?.locked ?? null,
        sessionId: status.session?.id ?? null,
        desktop: status.session?.desktop ?? null,
        checkedAt: Date.now(),
      });
      updatePC(pc.id, { lastSeenAt: Date.now() });
    } catch (error) {
      const message = error instanceof ApiError ? error.friendly : String(error);
      setStatus(pc.id, {
        reachable: false,
        locked: null,
        sessionId: null,
        desktop: null,
        checkedAt: Date.now(),
        error: message,
      });
    } finally {
      setBusy(null);
    }
  }, [pc, remember, setStatus, updatePC]);

  const wake = useCallback(async () => {
    if (!pc) return;
    setBusy("wake");
    setFeedback(null);
    wakeAbort.current?.abort();
    const controller = new AbortController();
    wakeAbort.current = controller;

    try {
      const result = await sendWakePackets(pc);
      if (result.packetsSent === 0) {
        setFeedback({ tone: "error", message: result.error ?? "Could not send a magic packet." });
        return;
      }

      setFeedback({
        tone: "info",
        message:
          `Sent ${result.packetsSent} magic packet${result.packetsSent === 1 ? "" : "s"}. ` +
          `Waiting for ${pc.name}…` +
          (result.broadcastBlocked ? " (iOS blocked broadcast; used its last known IP.)" : ""),
      });

      // Confirm rather than assume: poll until the PC actually answers.
      const awake = await waitUntilAwake(pc, { signal: controller.signal });
      if (controller.signal.aborted) return;

      if (awake) {
        setFeedback({ tone: "success", message: `${pc.name} is awake.` });
        await refresh();
      } else {
        setFeedback({
          tone: "error",
          message: result.broadcastBlocked
            ? `${pc.name} didn't come online. Only a unicast packet could be sent, which ` +
              `needs your router to still hold an ARP entry for ${pc.lastIp ?? "its IP"}. ` +
              `A DHCP reservation plus a static ARP entry makes that reliable.`
            : `${pc.name} didn't come online. The packet was sent, so check Wake-on-LAN ` +
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
  }, [pc, refresh]);

  const unlock = useCallback(async () => {
    if (!pc) return;
    setBusy("unlock");
    setFeedback(null);
    try {
      const endpoint = await resolveAndRemember(pc, remember);
      const result = await unlockSession(pc, endpoint);
      setFeedback({
        tone: "success",
        message: result.was_locked
          ? `Unlocked session ${result.session_id}.`
          : `${pc.name} was already unlocked.`,
      });
      setStatus(pc.id, {
        reachable: true,
        locked: false,
        sessionId: result.session_id,
        desktop: result.desktop,
        checkedAt: Date.now(),
      });
      updatePC(pc.id, { lastSeenAt: Date.now() });
    } catch (error) {
      setFeedback({
        tone: "error",
        message: error instanceof ApiError ? error.friendly : String(error),
      });
    } finally {
      setBusy(null);
    }
  }, [pc, remember, setStatus, updatePC]);

  const cancelWake = useCallback(() => {
    wakeAbort.current?.abort();
    setBusy(null);
  }, []);

  return { busy, feedback, setFeedback, refresh, wake, unlock, cancelWake };
}
