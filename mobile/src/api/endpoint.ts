/**
 * Working out which address actually reaches a PC.
 *
 * A PC has up to three plausible addresses: its `.local` hostname (which iOS
 * resolves natively through Bonjour), the IP that worked last time, and whatever
 * mDNS resolves right now. DHCP renewals invalidate the second, captive or
 * flaky networks can break the first, so all are raced and the winner cached.
 */

import { getLanDiscovery, isLanDiscoveryAvailable } from "@modules/lan-discovery";

import type { LinkedPC } from "@/state/types";

import { fetchServerInfo, type Endpoint } from "./client";
import { ApiError } from "./types";

const PROBE_TIMEOUT_MS = 2500;

/** Candidate addresses, best first, de-duplicated. */
export function candidateEndpoints(pc: LinkedPC): Endpoint[] {
  const seen = new Set<string>();
  const out: Endpoint[] = [];
  for (const host of [pc.hostname, pc.lastIp]) {
    if (!host) continue;
    const key = `${host}:${pc.port}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ host, port: pc.port });
  }
  return out;
}

/**
 * Probe every candidate concurrently and return the first that answers with the
 * *right* PC.
 *
 * The fingerprint check matters: on a network where another machine has taken
 * over the cached IP, an answer at that address is not this PC and must not be
 * treated as reachable.
 */
export async function resolveEndpoint(pc: LinkedPC): Promise<Endpoint> {
  const candidates = candidateEndpoints(pc);

  const attempts = candidates.map(
    (endpoint) =>
      new Promise<Endpoint>((resolve, reject) => {
        fetchServerInfo(endpoint, PROBE_TIMEOUT_MS)
          .then((info) =>
            info.fp === pc.serverFp
              ? resolve(endpoint)
              : reject(new ApiError("unreachable", "a different machine answered")),
          )
          .catch(reject);
      }),
  );

  if (attempts.length > 0) {
    try {
      return await Promise.any(attempts);
    } catch {
      /* fall through to mDNS */
    }
  }

  // Last resort: ask Bonjour where the instance lives now.
  if (isLanDiscoveryAvailable() && pc.instanceName) {
    try {
      const resolved = await getLanDiscovery().resolve(pc.instanceName);
      const endpoint = { host: resolved.host, port: resolved.port };
      const info = await fetchServerInfo(endpoint, PROBE_TIMEOUT_MS);
      if (info.fp === pc.serverFp) return endpoint;
    } catch {
      /* nothing else to try */
    }
  }

  throw new ApiError("unreachable", `no route to ${pc.name}`);
}

/** Resolve, then record the winning address so the next call starts there. */
export async function resolveAndRemember(
  pc: LinkedPC,
  remember: (patch: Partial<LinkedPC>) => void,
): Promise<Endpoint> {
  const endpoint = await resolveEndpoint(pc);
  const isIp = /^\d{1,3}(\.\d{1,3}){3}$/.test(endpoint.host);
  if (isIp && endpoint.host !== pc.lastIp) {
    remember({ lastIp: endpoint.host });
  }
  return endpoint;
}
