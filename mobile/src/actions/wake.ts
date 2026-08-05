/**
 * Waking a PC.
 *
 * The magic packet is sent *from the phone*, because when the PC is asleep its
 * service is not running and there is nobody to receive a request. The service's
 * `/v1/wake` endpoint is only a relay for waking other machines.
 *
 * Unicast before broadcast
 * ------------------------
 * iOS gates UDP *broadcast* on physical hardware behind the restricted
 * `com.apple.developer.networking.multicast` entitlement, which is only
 * obtainable through a paid Apple Developer Program team and an approval form.
 * A build signed with a free Apple ID cannot carry it, and broadcasts then fail
 * with EACCES.
 *
 * A magic packet does not actually need to be broadcast. The NIC matches on the
 * packet's *payload* (FF×6 followed by the MAC repeated 16 times), not on the
 * destination IP, so a unicast datagram aimed at the PC's last-known address
 * wakes it just as well -- provided the router still has an ARP entry for that
 * address. A DHCP reservation plus a static ARP entry makes that permanent.
 *
 * So unicast is tried first and broadcast second. On an entitled build both
 * work; on an unentitled one the unicast attempt carries the feature and the
 * broadcast failures are reported as a hint rather than as the whole story.
 */

import { getLanDiscovery, isLanDiscoveryAvailable } from "@modules/lan-discovery";

import { fetchServerInfo } from "@/api/client";
import { candidateEndpoints } from "@/api/endpoint";
import { t } from "@/i18n";
import type { LinkedPC } from "@/state/types";

export type WakeOutcome = {
  packetsSent: number;
  destinations: string[];
  /** Null when packets went out but we never confirmed the PC came up. */
  awake: boolean | null;
  /** True when every broadcast attempt failed but a unicast one succeeded. */
  broadcastBlocked: boolean;
  error?: string;
};

type Destination = { address: string; kind: "unicast" | "broadcast" };

const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 45_000;
const PROBE_TIMEOUT_MS = 1800;

const IPV4 = /^\d{1,3}(\.\d{1,3}){3}$/;

/** Looks like the sandbox refused a broadcast rather than the network failing. */
function looksLikePermissionDenied(message: string): boolean {
  return /eacces|errno 13|not permitted|permission denied/i.test(message);
}

/**
 * Where to aim, best chance first.
 *
 * The phone's own subnet broadcast is included alongside the one recorded at
 * pairing: if the phone has since moved to a different subnet, the recorded
 * address is no longer on-link.
 */
export function wakeDestinations(pc: LinkedPC, phoneBroadcasts: string[]): Destination[] {
  const out: Destination[] = [];
  const seen = new Set<string>();

  const push = (address: string | null | undefined, kind: Destination["kind"]) => {
    if (!address || !IPV4.test(address) || seen.has(address)) return;
    seen.add(address);
    out.push({ address, kind });
  };

  // Needs no entitlement, so it goes first.
  push(pc.lastIp, "unicast");

  push(pc.wake.broadcast, "broadcast");
  for (const broadcast of phoneBroadcasts) push(broadcast, "broadcast");

  return out;
}

/**
 * Broadcast a magic packet to every MAC the PC reported at pairing time.
 *
 * A machine with both wired and wireless NICs only needs one packet to land, and
 * we cannot tell from here which link is up.
 */
export async function sendWakePackets(pc: LinkedPC): Promise<WakeOutcome> {
  if (!isLanDiscoveryAvailable()) {
    return {
      packetsSent: 0,
      destinations: [],
      awake: null,
      broadcastBlocked: false,
      error: t("wake.needsDevBuild"),
    };
  }

  if (pc.wake.macs.length === 0) {
    return {
      packetsSent: 0,
      destinations: [],
      awake: null,
      broadcastBlocked: false,
      error: t("wake.noMacs"),
    };
  }

  const module = getLanDiscovery();

  let phoneBroadcasts: string[] = [];
  try {
    phoneBroadcasts = (await module.getBroadcastAddresses()).map((iface) => iface.broadcast);
  } catch {
    /* fall back to whatever the PC told us at pairing time */
  }

  const destinations = wakeDestinations(pc, phoneBroadcasts);
  const succeeded: string[] = [];
  let unicastWorked = false;
  let broadcastAttempted = false;
  let broadcastWorked = false;
  let permissionDenied = false;
  let lastError: string | undefined;

  for (const mac of pc.wake.macs) {
    for (const destination of destinations) {
      if (destination.kind === "broadcast") broadcastAttempted = true;
      try {
        const sent = await module.sendMagicPacket(
          mac,
          destination.address,
          pc.wake.port,
          null,
        );
        if (sent > 0) {
          succeeded.push(`${mac} → ${destination.address}:${pc.wake.port}`);
          if (destination.kind === "unicast") unicastWorked = true;
          else broadcastWorked = true;
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        lastError = message;
        if (destination.kind === "broadcast" && looksLikePermissionDenied(message)) {
          permissionDenied = true;
        }
      }
    }
  }

  const broadcastBlocked =
    broadcastAttempted && !broadcastWorked && (permissionDenied || unicastWorked);

  if (succeeded.length === 0) {
    return {
      packetsSent: 0,
      destinations: [],
      awake: null,
      broadcastBlocked,
      error: permissionDenied ? t("wake.noUnicastKnown") : (lastError ?? t("wake.nothingSent")),
    };
  }

  return {
    packetsSent: succeeded.length,
    destinations: succeeded,
    awake: null,
    broadcastBlocked,
  };
}

/**
 * Poll until the PC answers `/v1/server-info` with the fingerprint we pinned.
 *
 * Unauthenticated on purpose: this only decides whether to show "online", and
 * the fingerprint check is enough to know it is the right machine. Anything the
 * user actually *does* afterwards goes through a signed, verified call.
 */
export async function waitUntilAwake(
  pc: LinkedPC,
  options: { signal?: AbortSignal; onTick?: (elapsedMs: number) => void } = {},
): Promise<boolean> {
  const started = Date.now();

  while (Date.now() - started < POLL_TIMEOUT_MS) {
    if (options.signal?.aborted) return false;

    for (const endpoint of candidateEndpoints(pc)) {
      try {
        const info = await fetchServerInfo(endpoint, PROBE_TIMEOUT_MS);
        if (info.fp === pc.serverFp) return true;
      } catch {
        /* not up yet */
      }
    }

    options.onTick?.(Date.now() - started);
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
  }

  return false;
}
