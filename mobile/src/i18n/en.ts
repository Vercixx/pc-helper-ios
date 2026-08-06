/**
 * The source catalogue. Every other language is typed against this one, so a
 * key added here is a compile error everywhere else until it is translated.
 *
 * Placeholders are `{name}`-style and substituted by `t()`. A value that is an
 * object rather than a string is a plural: `count` picks the form, using the
 * language's own rules (`plural.ts`), which is why English carries only `one`
 * and `many` while Russian needs `few` as well.
 */

import type { Message, Plural } from "./plural";

export const en = {
  // Navigation titles.
  "nav.myPCs": "My PCs",
  "nav.addPC": "Add a PC",
  "nav.pair": "Pair",
  "nav.pairWithPC": "Pair with a PC",
  "nav.confirmPairing": "Confirm pairing",
  "nav.scan": "Scan QR code",
  "nav.camera": "Camera",
  "nav.settings": "Settings",

  // Shared.
  "common.cancel": "Cancel",
  "common.none": "none",

  // PC list.
  "list.empty.title": "No PCs yet",
  "list.empty.body": "On your Linux PC run {cmd}, then tap ＋ to scan the code it shows.",
  "list.a11y.addPC": "Add a PC",
  "list.a11y.rowHint": "Opens details. Long press for wake and unlock.",
  "list.a11y.settings": "Settings",

  // Status lines.
  "status.waking": "Waking…",
  "status.unlocking": "Unlocking…",
  "status.locking": "Locking…",
  "status.checking": "Checking…",
  "status.asleep": "Asleep or unreachable",
  "status.noUser": "Online — nobody logged in",
  "status.lockedHint": "Locked — long press to unlock",
  "status.unlockedHint": "Unlocked — long press to lock",
  "status.locked": "Locked",
  "status.unlocked": "Unlocked",

  // Actions.
  "action.wake": "Wake up",
  "action.unlock": "Unlock session",
  "action.lock": "Lock session",
  "action.refresh": "Refresh",
  "action.details": "Details",

  // Detail screen.
  "detail.gone": "This PC is no longer paired.",
  "detail.session": "Session {id}",
  "detail.address": "Address",
  "detail.lastIp": "Last IP",
  "detail.capabilities": "Capabilities",
  "detail.wakeTargets": "Wake targets",
  "detail.noTargets": "none configured",
  "detail.unlockConfirmation": "Unlock confirmation",
  "detail.confirmNone": "None",
  "detail.confirmBiometric": "Face ID / passcode",
  "detail.deviceId": "This device's ID",
  "detail.fingerprint": "PC fingerprint",
  "detail.pairedAt": "Paired",
  "detail.widgetStorage": "Widget storage",
  "detail.unpair": "Unpair this PC",
  "detail.unpair.title": "Unpair {name}?",
  "detail.unpair.body":
    "This phone's key will be deleted. The PC will keep its record until you revoke it there with 'wol-unlockctl revoke'.",
  "detail.unpair.confirm": "Unpair",

  // Widget storage diagnostics.
  "widget.ok": "ok",
  "widget.notWritable": "not writable",
  "widget.noGroup": "no App Group in the signed profile",
  "widget.grants": "profile grants: {keys}",
  "widget.unreadable": "profile present but unreadable",
  "widget.noProfile": "no provisioning profile",

  // Discovery sheet.
  "discover.scan.title": "Scan QR code",
  "discover.scan.body": "The fastest way. Run {cmd} on the PC.",
  "discover.manual.title": "Enter details manually",
  "discover.manual.body": "If the PC is on another subnet or discovery is blocked.",
  "discover.section": "ON THIS NETWORK",
  "discover.unavailable.title": "Discovery unavailable",
  "discover.unavailable.body":
    "Bonjour browsing needs a development build. Use the QR code instead.",
  "discover.failed": "Couldn't browse the network",
  "discover.looking": "Looking for PCs…",
  "discover.paired": "Paired",
  "discover.pairingOpen": "Pairing open",
  "discover.a11y.alreadyPaired": "{name}, already paired",
  "discover.footnote":
    "Discovered names and fingerprints are hints only. Pairing checks the PC's identity against the code you enter before trusting it.",

  // Pairing screen.
  "pair.code.label": "PAIRING CODE",
  "pair.code.hint": "Shown by {cmd} on the PC. It expires after two minutes.",
  "pair.code.a11y": "Pairing code",
  "pair.address.label": "PC ADDRESS",
  "pair.host.a11y": "PC hostname",
  "pair.port.a11y": "Port",
  "pair.port.range": "Port must be between 1 and 65535.",
  "pair.identity.label": "PC IDENTITY",
  "pair.identity.scanned":
    "From the QR code. Pairing stops if the PC presents anything else.",
  "pair.identity.manual": "Check this matches the fingerprint shown on the PC.",
  "pair.waiting.title": "Waiting for approval",
  "pair.waiting.body": "Confirm this device at the PC. Compare the fingerprint it shows.",
  "pair.with": "Pairing with “{name}”.",
  "pair.contacting": "Contacting PC…",
  "pair.waiting": "Waiting…",
  "pair.submit": "Pair",

  // Scanner.
  "scan.notATicket": "That isn't a PC Unlock pairing code.",
  "scan.permission.title": "Camera access needed",
  "scan.permission.body": "The pairing code is shown as a QR code on your PC's screen.",
  "scan.permission.allow": "Allow camera",
  "scan.hint": "Point at the QR code shown by wol-unlockctl pair",

  // Wake.
  "wake.failed": "Could not send a magic packet.",
  "wake.sent": {
    one: "Sent {count} magic packet. Waiting for {name}…",
    many: "Sent {count} magic packets. Waiting for {name}…",
  },
  "wake.sent.broadcastBlocked": " (iOS blocked broadcast; used its last known IP.)",
  "wake.awake": "{name} is awake.",
  "wake.noResponse":
    "{name} didn't come online. The packet was sent, so check Wake-on-LAN is enabled in its BIOS and NIC.",
  "wake.noResponse.unicast":
    "{name} didn't come online. Only a unicast packet could be sent, which needs your router to still hold an ARP entry for {ip}. A DHCP reservation plus a static ARP entry makes that reliable.",
  "wake.itsIp": "its IP",
  "wake.needsDevBuild":
    "Wake-on-LAN needs a development build — Expo Go cannot open a UDP socket.",
  "wake.noMacs": "This PC reported no MAC addresses to wake.",
  "wake.noUnicastKnown":
    "iOS blocked the broadcast, and no unicast address is known for this PC yet. Open it once while it's awake so its IP is recorded, then try again.",
  "wake.nothingSent": "no magic packet could be sent",

  // Unlock.
  "unlock.prompt": "Unlock {name}",
  "unlock.cancelled": "Cancelled.",
  "unlock.done": "Unlocked session {id}.",
  "unlock.alreadyUnlocked": "{name} was already unlocked.",

  "lock.done": "Locked session {id}.",
  "lock.alreadyLocked": "{name} was already locked.",

  // Errors, keyed by the protocol's error codes (PROTOCOL.md 4.1).
  "error.unreachable": "Can't reach this PC. Is it awake and on the same Wi-Fi?",
  "error.device_revoked": "This phone's access was revoked. Pair with the PC again.",
  "error.unknown_device": "This PC doesn't recognise this phone. Pair again.",
  "error.timestamp_out_of_window": "Your phone's clock is out of sync with the PC.",
  "error.no_session": "Nobody is logged in on that PC, so there's no session to lock or unlock.",
  "error.rate_limited": "Too many requests. Wait a moment and try again.",
  "error.forbidden_network": "The PC refused this network. Connect to the same LAN.",
  "error.bad_signature":
    "The reply wasn't signed by this PC. Someone may be impersonating it.",
  "error.invalid_code": "That pairing code isn't right.",
  "error.pairing_closed":
    "The pairing window closed. Run 'wol-unlockctl pair' on the PC again.",
  "error.pairing_denied": "The PC declined this device.",
  "error.pairing_timeout": "Nobody approved this device at the PC.",

  // Settings.
  "settings.language": "LANGUAGE",
  "settings.language.system": "System",
  "settings.language.note":
    "Shortcuts, the widget and iOS permission prompts always follow the system language, because iOS resolves those before the app runs.",
} satisfies Record<string, Message>;

export type MessageKey = keyof typeof en;

/** Every language must answer for every key, with the same plural-ness. */
export type Catalog = {
  [K in MessageKey]: (typeof en)[K] extends string ? string : Plural;
};
