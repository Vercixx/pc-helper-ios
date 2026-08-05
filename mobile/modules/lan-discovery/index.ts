import { NativeModule, requireNativeModule } from "expo";
import { Platform } from "react-native";

/** TXT record contents advertised by the PC service (PROTOCOL.md section 8). */
export type ServiceTxt = {
  /** TXT schema version. */
  v?: string;
  /** HTTP API version. */
  api?: string;
  /** Human-readable display name. */
  name?: string;
  /** Comma-separated capabilities, e.g. "status,unlock,wol". */
  caps?: string;
  /** base64url SHA-256 of the server's Ed25519 public key. */
  fp?: string;
  /** "1" while a pairing window is open. */
  pair?: string;
};

export type DiscoveredService = {
  /** Bonjour instance name -- the PC's hostname. */
  name: string;
  type: string;
  domain: string;
  txt: ServiceTxt;
  /** `${name}.local`, which survives DHCP lease changes. */
  hostname: string;
};

export type ResolvedService = {
  name: string;
  /** Concrete address or hostname the SRV record resolved to. */
  host: string;
  hostname: string;
  port: number;
};

export type BroadcastInterface = {
  name: string;
  address: string;
  broadcast: string;
  isWiFi: boolean;
};

export type BrowseState = {
  state: "ready" | "failed" | "cancelled" | "waiting";
  error?: string;
};

type LanDiscoveryEvents = {
  onServiceFound: (service: DiscoveredService) => void;
  onServiceLost: (service: { name: string }) => void;
  onBrowseStateChange: (state: BrowseState) => void;
};

declare class LanDiscoveryNativeModule extends NativeModule<LanDiscoveryEvents> {
  startBrowsing(serviceType?: string): Promise<void>;
  stopBrowsing(): Promise<void>;
  resolve(name: string, serviceType?: string): Promise<ResolvedService>;
  getBroadcastAddresses(): Promise<BroadcastInterface[]>;
  sendMagicPacket(
    mac: string,
    broadcast: string,
    port: number,
    secureOn?: string | null,
  ): Promise<number>;
}

/**
 * Native Bonjour browsing and Wake-on-LAN.
 *
 * Only present in a development or production build. Expo Go cannot load custom
 * native code, so the module is loaded defensively and callers should check
 * {@link isLanDiscoveryAvailable} before relying on it.
 */
let nativeModule: LanDiscoveryNativeModule | null = null;

try {
  if (Platform.OS === "ios") {
    nativeModule = requireNativeModule<LanDiscoveryNativeModule>("LanDiscovery");
  }
} catch {
  nativeModule = null;
}

export const isLanDiscoveryAvailable = (): boolean => nativeModule !== null;

export function getLanDiscovery(): LanDiscoveryNativeModule {
  if (!nativeModule) {
    throw new Error(
      "The LanDiscovery native module is not loaded. Discovery and Wake-on-LAN " +
        "need a development build; they cannot work in Expo Go. Run: npx expo run:ios",
    );
  }
  return nativeModule;
}

export default nativeModule;
