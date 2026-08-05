/**
 * Live mDNS browsing for `_wol-unlock._tcp`.
 *
 * Results are hinting only. The fingerprint in the TXT record lets the UI mark a
 * discovered PC as already-paired and lets pairing check that the machine it is
 * about to trust is the one whose QR code was scanned -- but nothing here is
 * trusted on its own.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  type BrowseState,
  type DiscoveredService,
  getLanDiscovery,
  isLanDiscoveryAvailable,
} from "@modules/lan-discovery";

export type DiscoveredPC = {
  instanceName: string;
  hostname: string;
  displayName: string;
  fingerprint: string;
  capabilities: string[];
  pairingOpen: boolean;
  apiVersion: string;
};

function toDiscoveredPC(service: DiscoveredService): DiscoveredPC {
  const txt = service.txt ?? {};
  return {
    instanceName: service.name,
    hostname: service.hostname,
    displayName: txt.name?.trim() || service.name,
    fingerprint: txt.fp ?? "",
    capabilities: (txt.caps ?? "").split(",").filter(Boolean),
    pairingOpen: txt.pair === "1",
    apiVersion: txt.api ?? "",
  };
}

export type DiscoveryResult = {
  available: boolean;
  services: DiscoveredPC[];
  state: BrowseState["state"] | "idle";
  error: string | null;
  restart: () => void;
};

export function useDiscovery(enabled = true): DiscoveryResult {
  const available = useMemo(() => isLanDiscoveryAvailable(), []);
  const [services, setServices] = useState<Record<string, DiscoveredPC>>({});
  const [state, setState] = useState<BrowseState["state"] | "idle">("idle");
  const [error, setError] = useState<string | null>(null);
  const [generation, setGeneration] = useState(0);
  const mounted = useRef(true);

  const restart = useCallback(() => {
    setServices({});
    setError(null);
    setGeneration((value) => value + 1);
  }, []);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!enabled) return;
    if (!available) {
      setState("failed");
      setError(
        "Discovery needs a development build. Add the PC by scanning its QR code instead.",
      );
      return;
    }

    const module = getLanDiscovery();

    const foundSub = module.addListener("onServiceFound", (service) => {
      if (!mounted.current) return;
      const entry = toDiscoveredPC(service);
      setServices((current) => ({ ...current, [entry.instanceName]: entry }));
    });

    const lostSub = module.addListener("onServiceLost", ({ name }) => {
      if (!mounted.current) return;
      setServices((current) => {
        if (!(name in current)) return current;
        const next = { ...current };
        delete next[name];
        return next;
      });
    });

    const stateSub = module.addListener("onBrowseStateChange", (update) => {
      if (!mounted.current) return;
      setState(update.state);
      setError(
        update.state === "waiting"
          ? "Waiting for permission to use the local network. Allow it in Settings if you declined."
          : (update.error ?? null),
      );
    });

    module.startBrowsing().catch((cause: unknown) => {
      if (!mounted.current) return;
      setState("failed");
      setError(cause instanceof Error ? cause.message : String(cause));
    });

    return () => {
      foundSub.remove();
      lostSub.remove();
      stateSub.remove();
      module.stopBrowsing().catch(() => {
        /* the browser is being torn down anyway */
      });
    };
  }, [available, enabled, generation]);

  const sorted = useMemo(
    () =>
      Object.values(services).sort((a, b) =>
        a.displayName.localeCompare(b.displayName, undefined, { sensitivity: "base" }),
      ),
    [services],
  );

  return { available, services: sorted, state, error, restart };
}
