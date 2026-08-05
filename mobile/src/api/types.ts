/** Wire types for protocol v1. Mirrors `docs/PROTOCOL.md` section 5. */

export type ApiEnvelope<T> =
  | { ok: true; ts: number; data: T }
  | { ok: false; ts: number; error: { code: string; message: string } };

export type ServerInfo = {
  v: number;
  api: number;
  name: string;
  fp: string;
  caps: string[];
  pair: boolean;
};

export type SessionInfo = {
  id: string;
  type: string;
  class: string;
  active: boolean;
  locked: boolean;
  seat: string | null;
  desktop: string | null;
};

export type WakeTargetInfo = {
  mac: string;
  iface: string | null;
  broadcast: string;
  port: number;
  link: "up" | "down" | string;
};

export type StatusResponse = ServerInfo & {
  uptime_s: number;
  session: SessionInfo | null;
  wake_targets: WakeTargetInfo[];
  pairing: { active: boolean; state?: string; expires_in_s?: number };
};

export type UnlockResponse = {
  session_id: string;
  was_locked: boolean;
  unlocked: boolean;
  type: string;
  desktop: string | null;
  seat: string | null;
};

export type WakeResponse = {
  sent: { mac: string; via: string; bytes: number }[];
};

export type PairResponse = {
  device_id: string;
  server_pubkey: string;
  server_fp: string;
  name: string;
  api: number;
  caps: string[];
  wake?: { macs: string[]; broadcast: string; port: number };
};

/** Every error code the service can return (PROTOCOL.md 4.1). */
export type ApiErrorCode =
  | "bad_request"
  | "forbidden_network"
  | "unknown_device"
  | "device_revoked"
  | "timestamp_out_of_window"
  | "replayed_nonce"
  | "body_hash_mismatch"
  | "invalid_signature"
  | "rate_limited"
  | "pairing_disabled"
  | "invalid_code"
  | "pairing_expired"
  | "pairing_denied"
  | "pairing_timeout"
  | "no_session"
  | "unlock_failed"
  | "wake_failed"
  | "not_allowed"
  | "internal_error"
  // Client-side conditions, never sent by the server.
  | "unreachable"
  | "unsigned_response"
  | "bad_server_signature"
  | "malformed_response";

export class ApiError extends Error {
  readonly code: ApiErrorCode;
  readonly status: number;

  constructor(code: ApiErrorCode, message: string, status = 0) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }

  /** A sentence to put in front of the user. */
  get friendly(): string {
    switch (this.code) {
      case "unreachable":
        return "Can't reach this PC. Is it awake and on the same Wi-Fi?";
      case "device_revoked":
        return "This phone's access was revoked. Pair with the PC again.";
      case "unknown_device":
        return "This PC doesn't recognise this phone. Pair again.";
      case "timestamp_out_of_window":
        return "Your phone's clock is out of sync with the PC.";
      case "no_session":
        return "Nobody is logged in on that PC, so there's no session to unlock.";
      case "unlock_failed":
        return this.message;
      case "rate_limited":
        return "Too many requests. Wait a moment and try again.";
      case "forbidden_network":
        return "The PC refused this network. Connect to the same LAN.";
      case "bad_server_signature":
      case "unsigned_response":
        return "The reply wasn't signed by this PC. Someone may be impersonating it.";
      case "invalid_code":
        return "That pairing code isn't right.";
      case "pairing_expired":
      case "pairing_disabled":
        return "The pairing window closed. Run 'wol-unlockctl pair' on the PC again.";
      case "pairing_denied":
        return "The PC declined this device.";
      case "pairing_timeout":
        return "Nobody approved this device at the PC.";
      default:
        return this.message;
    }
  }
}
