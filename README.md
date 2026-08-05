# wol-unlock

Wake a Linux PC and unlock its desktop session from an iPhone, over the LAN, with
no passwords anywhere.

```
iPhone (Expo / SwiftUI)                      my-pc (systemd --user)
├─ Ed25519 key in the Keychain, Face ID      ├─ mDNS  _wol-unlock._tcp
├─ signed HTTP  ─────────────────────────▶   ├─ aiohttp :8765, signature-verified
└─ UDP magic packet ─────────────────────▶   └─ loginctl unlock-session
   (works while the PC is asleep)               no sudo · no polkit · no setuid
```

| | |
|---|---|
| **Protocol** | [`docs/PROTOCOL.md`](docs/PROTOCOL.md) — normative, with test vectors |
| **PC service** | [`pc-service/`](pc-service/) — Python 3.11+, aiohttp, zeroconf |
| **iOS app** | [`mobile/`](mobile/) — Expo SDK 57, `@expo/ui` SwiftUI |
| **Installing on a phone** | [`docs/SIDELOADING.md`](docs/SIDELOADING.md) — including the free-account route |
| **Shortcuts & Siri** | [`docs/SHORTCUTS.md`](docs/SHORTCUTS.md) — Wake / status / unlock as App Intents |
| **Widgets** | [`docs/WIDGETS.md`](docs/WIDGETS.md) — WidgetKit and Control Center, pending an App Group that survives a sideload |

---

## Why it is built this way

**No passwords, no shared secrets.** Each phone holds its own Ed25519 keypair.
The PC stores only public keys. Every request is signed over a canonical string
that includes a timestamp, a single-use nonce, a hash of the body, and *the
server's own fingerprint* — so a request captured on one PC is worthless against
another.

**No privilege escalation.** `org.freedesktop.login1.policy` defines no
`unlock-session` action; logind consults polkit only when the caller's uid
differs from the session's. Running as the desktop user therefore needs no sudo,
no setuid binary, and no polkit rule. The systemd unit can then be locked down
hard (`ProtectSystem=strict`, `ProtectHome=read-only`, `NoNewPrivileges`,
`SystemCallFilter=@system-service`) because nothing it does requires privilege.

**Pairing needs physical access, structurally.** Opening a pairing window is only
reachable over a `0600` Unix socket in `$XDG_RUNTIME_DIR`, guarded by an
`SO_PEERCRED` uid check. There is no HTTP route to it, so "you must be at the
machine" is a property of the transport rather than a rule a handler could forget
to enforce.

**The phone sends the magic packet, not the PC.** When a PC is asleep its service
is not running, so it cannot receive "please wake up". `POST /v1/wake` exists, but
only as a relay for waking *other* machines.

**Results are signed too.** Responses carry a server signature over the body and
the request's nonce, so `"unlocked": true` cannot be forged by a LAN attacker,
and a recorded reply cannot be replayed against a later request.

---

## Setting up the PC

```bash
cd pc-service
./scripts/install.sh          # venv, config, systemd --user unit; no root
```

The installer detects your interfaces, writes a commented config, starts the
service, and tells you the firewall rules you need. Then, once, as root:

```bash
sudo ./scripts/enable-wol.sh  # arms the NIC + writes a udev rule
```

…and enable **Wake on LAN** in your BIOS/UEFI. Without that the NIC is armed but
the board ignores the packet.

### Day-to-day

```bash
wol-unlockctl pair            # opens a 2-minute window, prints a code + QR
wol-unlockctl status          # service, session, wake targets
wol-unlockctl devices         # trusted phones and when each was last seen
wol-unlockctl revoke <name>   # cut a phone off
wol-unlockctl audit           # recent activity
wol-unlockctl discover        # is the mDNS advertisement visible?
journalctl --user -u wol-unlock -f
```

Configuration lives in `~/.config/wol-unlock/config.toml`; state (the server key,
the device table, the replay cache) in `~/.local/share/wol-unlock/`.

### Screen locker support

`loginctl unlock-session` emits logind's `Unlock` signal — the locker has to act
on it. **KDE Plasma and GNOME do.** Bare `swaylock` and `i3lock` do not and cannot
be unlocked remotely. The service detects this: it re-reads `LockedHint` after
signalling and reports `unlock_failed` rather than trusting a zero exit code.

---

## Building the app

You need a **development build** — Expo Go cannot load the native module that does
Bonjour browsing and opens the UDP socket.

**With a paid Apple Developer account:**

```bash
cd mobile
npm install
eas build --profile development --platform ios
```

**Without one**, EAS cannot help: its `internal` distribution needs an ad-hoc
provisioning profile, which is a Developer Program feature. Build unsigned and
sign on the phone instead — run the **Build unsigned iOS IPA** workflow in the
Actions tab, then install the artifact with SideStore or AltStore. Full
instructions, and what a free signature cannot do, are in
[`docs/SIDELOADING.md`](docs/SIDELOADING.md).

Then pair: tap **＋**, scan the QR that `wol-unlockctl pair` prints, and approve
the device at the PC. Long-press a PC in the list for **Wake up** / **Unlock
session**.

### Wake-on-LAN and the multicast entitlement

iOS gates UDP *broadcast* on physical devices behind
`com.apple.developer.networking.multicast`, which needs a paid team and Apple's
approval. The app therefore aims the magic packet at the PC's **last-known IP
first** and only then tries broadcast — a NIC matches the packet's payload, not
its destination IP, so unicast wakes the machine just as well. Give the PC a DHCP
reservation and a static ARP entry on the router so the address stays resolvable
while it sleeps. Discovery and unlocking are unaffected.

---

## Verifying it

```bash
cd pc-service && .venv/bin/python -m pytest -q     # 194 tests
cd mobile      && npm test                          # 30 tests
```

Both suites assert the *same* vectors from `docs/PROTOCOL.md`, so the Python and
TypeScript implementations are checked against one specification rather than
against each other.

There is also a self-contained reference client that implements the protocol
straight from the spec — useful for exercising the whole flow without a phone:

```bash
cd pc-service
wol-unlockctl pair                                   # note the code
python tests/refclient.py pair --code XXXXXXXX --host my-pc.local
python tests/refclient.py status
python tests/refclient.py selftest                   # every negative case
```

`selftest` checks that replays, stale and future timestamps, tampered bodies,
wrong keys, cross-server signatures, non-allowlisted wake targets, broadcast
addresses outside the LAN, and query strings on signed routes are all rejected.

To prove the unlock actually works end to end:

```bash
loginctl lock-session 1 && sleep 2
loginctl show-session 1 -p LockedHint     # LockedHint=yes
python tests/refclient.py unlock
loginctl show-session 1 -p LockedHint     # LockedHint=no   ← the real proof
```

---

## What this does not protect against

- **Anyone holding your unlocked phone can unlock the PC.** That is the feature.
  Face ID on the signing key is the mitigation and is on by default.
- **Magic packets are unauthenticated by design** — anyone on the LAN can wake the
  machine. Waking is not a privileged action.
- **No TLS**, so a LAN observer sees which action was requested and when. They
  cannot forge, replay, or alter it. Noise_IK over the same identities is the
  documented upgrade path.
- **WAN exposure is a non-goal.** Reach the LAN over a VPN instead. Requests
  from outside `http.allowed_networks` are dropped before any parsing, but that
  is the service enforcing it, not the kernel: `IPAddressDeny=` needs root and
  is silently ignored in a `--user` unit, so it is not used here.
