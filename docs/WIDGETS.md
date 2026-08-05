# Widgets and Control Center

> **Status: the target builds again, and is unverified on device.** The earlier
> conclusion — that SideStore does not grant this app an App Group — was a
> symptom, not the cause: the CI build was unsigned, so the entitlement was not
> in the binaries for SideStore to find. See [Sideloading](#sideloading) below.
> Whether the group survives a real install is now a question one sideload
> answers.
>
> The same three actions are available through **Shortcuts** regardless, as App
> Intents in the app target — see [SHORTCUTS.md](SHORTCUTS.md). Those need no
> entitlement at all and do work.

A WidgetKit extension (`mobile/targets/widget`) that shows whether the PC is
awake and locked, and can wake it — from the Home Screen, the Lock Screen, and
Control Center.

## What it can and cannot do

| Surface | Shows status | Wake | Unlock |
| --- | --- | --- | --- |
| Home Screen widget (small / medium) | yes | yes | **no** |
| Lock Screen widget (circular / rectangular) | yes | no | **no** |
| Control Center / Lock Screen control (iOS 18+) | — | yes | **no** |

Unlock is deliberately absent from all of them.

Control Center and the Lock Screen are reachable **without unlocking the phone**.
A wake button there gives nothing away: a magic packet is unauthenticated UDP
that anyone already on the LAN can send, and it cannot do more than power a
machine on. An unlock button is the opposite — it would hand anyone holding the
phone a one-tap way into a desktop session, which is precisely what the Face ID
gate in the app exists to prevent. Unlocking stays in the app.

## Architecture

An extension is a separate process with its own container. It cannot read the
app's AsyncStorage, and by default it cannot read the app's keychain items
either. Two channels bridge that gap.

```
   app (com.vercixx.wolunlock)                 extension (….widget)
   ───────────────────────────                 ────────────────────
   zustand store
     │  src/state/widgetBridge.ts
     ▼
   App Group UserDefaults  ──────────────────▶ SharedState.swift
   group.com.vercixx.wolunlock                   name, address, MACs,
     key "wolunlock.state"                       pinned server key,
     (JSON, no secrets)                          last known lock state

   keychain, access group                        DeviceKey.swift
   group.com.vercixx.wolunlock ──────────────▶     Ed25519 seed, by alias
     via expo-secure-store                         → StatusClient.swift
```

The App Group carries only what the app already keeps unencrypted: addresses,
public identities, and the last status it saw. The Ed25519 seed stays in the
keychain and is reached separately, by alias.

### The protocol, a third time

`targets/widget/Protocol.swift` is a Swift implementation of the same normative
spec as `pc-service/.../canonical.py` and `mobile/src/crypto/canonical.ts`. It
covers what a read-only client needs: base64url, the canonical request and
response strings, SHA-256, Ed25519 signing via CryptoKit, and fingerprints.

`StatusClient.swift` signs `GET /v1/status` and **verifies the server's
signature before parsing the body** — same as the app. Without that second half,
anything on the LAN could tell the widget the PC is awake and unlocked.

`Curve25519.Signing.PrivateKey(rawRepresentation:)` takes the RFC 8032 seed, so
CryptoKit consumes exactly the bytes `@noble/ed25519` produced in the app.

### Degradation is explicit

Three things can fail independently, and the widget names which:

| Widget shows | Meaning |
| --- | --- |
| `Not paired` / "Open PC Unlock" | the extension sees no App Group state |
| `cached · 6m ago` plus a reason | the keychain read or the request failed; showing what the app last saw |
| `Asleep` with no footnote | a live, verified check found nothing listening |

That distinction is the point. "cached" and "Asleep" look similar on screen and
mean entirely different things, and on a sideloaded build the difference is
usually an entitlement, not a sleeping computer. The medium widget prints the
underlying error.

## Entitlements

Both targets need the App Group `group.com.vercixx.wolunlock`. It is declared
once in `mobile/app.json` under `ios.entitlements` and mirrored into the target
by `targets/widget/expo-target.config.js`.

The App Group identifier doubles as the **keychain access group**. That is a
deliberate choice over `$(AppIdentifierPrefix)com.vercixx.wolunlock`: the app
group is a literal the extension can name at compile time, whereas the
identifier prefix depends on whichever team signed the build — unknowable from
Swift source that has to work under any signing identity.

`src/crypto/keys.ts` writes seeds into the shared group and falls back to the
app-private default if that is refused, promoting existing seeds on first read.
A PC paired before widgets existed becomes visible to the widget without
re-pairing, and an app whose App Group entitlement was stripped keeps working
with widgets simply showing cached data.

### Sideloading

App Groups are one of the capabilities Apple restricts to paid Developer Program
memberships; a free Personal Team cannot provision them through Xcode. The
AltStore family (SideStore among them) works around this during signing: it
registers the group under its own team, renaming it to
`group.com.vercixx.wolunlock.<TEAMID>`, and rewrites the entitlement to match.
That rename is why nothing may hardcode the identifier — see
`WUEntitlements.swift`.

**The entitlement has to be in the binary for any of that to happen.** SideStore
discovers what an app needs by reading the entitlements out of each Mach-O's
code signature — AltSign's `ALTApplication` calls `ldid::Entitlements` — and
never reads an entitlements file shipped beside the `.ipa`. An unsigned build
carries no such blob, so the installer concludes the app uses no App Groups,
turns the feature off on the App ID, registers no group, and issues a profile
without one. The app and the widget are then signed into separate sandboxes
with no shared container, silently, and the widget shows "Not paired" forever.

`.github/workflows/ios-unsigned.yml` therefore ad-hoc signs each bundle with its
entitlements after building — extensions before the app, as codesign requires —
purely so the installer can read them; the ad-hoc signature is replaced at
install time. A following step fails the build if
`com.apple.security.application-groups` is missing from any bundle's signature.

Two things can still go wrong on the phone, and both are visible rather than
silent: `addAppGroup` can be refused for the team, which SideStore logs as
`Failed to create new App Group` and then continues without one; and the app can
end up naming a group it holds no container for, which `publish` now reports as
a failed write instead of returning success for a write that went nowhere.

### Install over an existing copy and the extension disappears

An App Group that works is not enough — the `.appex` also has to survive the
install. SideStore's `RemoveAppExtensionsOperation` deletes any extension it
considers *excess*, and excess is computed against **what the installed copy
already has**:

```swift
let excessExtensionsInTargetApp = targetAppEx.filter {
    !(existingAppExNames.contains($0.bundleIdentifier))
}
```

Updating an install that had no widget therefore removes the widget, because it
is new. Normally that is a prompt — an "App Contains Extensions" alert offering
*Use Main Profile*, *Register App ID for Each Extension*, *Remove*, or *Choose* —
but the prompt needs `customizeAppExtensions` (on by default for a free team,
under Settings → Advanced → User Customizations) **and** SideStore in the
foreground with a live view controller. Without both it takes the silent path
and removes the extension with no trace. The app installs, the App Group works,
the widget storage row reads "ok", and the widget is absent from Add Widget.

A fresh install has nothing to compare against — `localAppExtensions == nil`
short-circuits to keeping everything. **So: delete the app first, then install
with SideStore in the foreground.** Keeping the extension costs a second App ID
against the free account's ten per week, unless *Use Main Profile* is chosen.

## Known limits

- **One PC.** The widget acts on the first paired PC. Choosing between several
  needs an `AppIntentConfiguration` so each widget instance can be configured.
- **Locked-phone refreshes show cached data.** The seed is stored
  `WhenUnlockedThisDeviceOnly`, so a timeline refresh while the phone is locked
  cannot sign a status request. This is why nothing on the Lock Screen depends
  on the key.
- **Wake from the widget is unicast-first.** UDP broadcast needs the multicast
  entitlement, which requires a paid team *and* Apple's approval. Unicast wake
  depends on the router still holding an ARP entry for the sleeping PC — a DHCP
  reservation plus a static ARP entry makes it reliable.
- **Refresh cadence is WidgetKit's decision.** The timeline asks for 15 minutes;
  the system grants what it feels like. The app pushes a reload whenever its own
  view of a PC changes, which in practice is what keeps the widget current.
