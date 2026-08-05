# Getting the app onto an iPhone without a paid Apple account

EAS Build cannot help here. Its `development` and `preview` profiles both use
`distribution: "internal"`, which requires an **ad-hoc provisioning profile** — a
Developer Program feature. Logging in to a free Apple ID authenticates fine and
then fails at certificate creation, because a free "personal team" is not exposed
through the developer-portal API that EAS drives. The only EAS build needing no
credentials is a *simulator* build, which produces a simulator-architecture
`.app` you cannot install on a phone (and cannot run at all on Linux).

The route that does work: **build unsigned, sign on the phone.**

```
GitHub Actions (macOS runner)          iPhone
├─ expo prebuild                       ├─ SideStore / AltStore
├─ xcodebuild CODE_SIGNING_ALLOWED=NO  │    signs with your free Apple ID
└─ zip Payload/ → .ipa  ──────────────▶└─ installs, valid 7 days
```

---

## 1. Build the unsigned IPA

Push this repository to GitHub, then run the **Build unsigned iOS IPA** workflow
from the Actions tab (`.github/workflows/ios-unsigned.yml`). It runs on demand and
on `v*` tags rather than on every push, because macOS runners bill at a 10×
minute multiplier on private repositories. They are free on public ones.

The workflow typechecks, runs both test suites, generates the native project,
builds with signing disabled, embeds each bundle's entitlements with an ad-hoc
signature, verifies the App Group is present in every bundle and that the binary
is device- and not simulator-architecture, then uploads
`wol-unlock-unsigned.ipa` as an artifact.

The ad-hoc step is not optional. Signing tools read what an app needs out of its
code signature, so an entitlement absent from the binary is an entitlement the
signer will not ask Apple for — which is how the widget lost its App Group.
See [WIDGETS.md](WIDGETS.md#sideloading).

To build it on a Mac instead:

```bash
cd mobile
npm ci --legacy-peer-deps
npx expo prebuild --platform ios --clean
xcodebuild -workspace ios/*.xcworkspace -scheme "$(basename ios/*.xcworkspace .xcworkspace)" \
  -configuration Release -sdk iphoneos -derivedDataPath build \
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY="" build

app="$(ls -d build/Build/Products/Release-iphoneos/*.app | head -n1)"
# Nested code first, then extensions, then the app.
find "$app" -depth \( -name "*.framework" -o -name "*.dylib" \) \
  -exec codesign --force --sign - {} \;
for ext in "$app"/PlugIns/*.appex; do
  name="$(basename "$ext" .appex)"
  codesign --force --sign - --entitlements "ios/.targets/$name/generated.entitlements" "$ext"
done
codesign --force --sign - --entitlements ios/PCUnlock/PCUnlock.entitlements "$app"
codesign -d --entitlements :- "$app"   # should list application-groups

mkdir -p Payload && cp -R "$app" Payload/
zip -qry wol-unlock-unsigned.ipa Payload && rm -rf Payload
```

## 2. Sign and install it

Any of these will sign the IPA with a free Apple ID:

| Tool | Needs a computer? |
|---|---|
| **SideStore** | Only for first-time setup; refreshes on-device after |
| **AltStore** | Yes — AltServer on Windows or macOS, on the same network |
| **Sideloadly** | Yes, each time |

Free-account limits, which are Apple's and not this project's: apps expire after
**7 days**, you get **3 sideloaded apps** at a time, and **10 app IDs per week**.

---

## 3. What a free signature cannot do

Free provisioning cannot carry the restricted
`com.apple.developer.networking.multicast` entitlement, which iOS requires before
an app may send UDP **broadcast** on physical hardware. Without it,
`sendMagicPacket` to `192.168.1.255` fails with `EACCES`.

The app is built for this. `src/actions/wake.ts` aims at the PC's **last-known IP
first** and only then tries broadcast. A magic packet is matched on its payload —
`FF×6` followed by the MAC repeated 16 times — not on the destination IP, so a
unicast datagram wakes the machine just as well.

The one requirement is that your router still has an **ARP entry** for that IP
when the PC is asleep. Make it permanent:

1. Give the PC a **DHCP reservation** so its address never changes.
2. Add a **static ARP entry** on the router mapping that IP to the PC's MAC.

Most consumer routers offer both under LAN settings. On OpenWrt:

```
config host
    option ip   '192.168.1.50'
    option mac  '00:00:5e:00:53:01'
```

If the app reports *"iOS blocked the broadcast"* and the PC does not wake, this
ARP entry is what is missing. Open the PC once in the app while it is awake so
its IP gets recorded, then try waking it.

**Unaffected by any of this:** mDNS discovery (it goes through a system service
and needs only `NSLocalNetworkUsageDescription` + `NSBonjourServices`) and
unlocking (ordinary unicast HTTP). Only the wake broadcast is gated.

---

## If you later join the Developer Program

Nothing in the app needs to change; the unicast-first order stays a sensible
default. To enable broadcast as well:

1. Add `com.apple.developer.networking.multicast` to the iOS entitlements.
2. Request it from Apple — approval is manual and is not instant.
3. Build with `eas build --profile development --platform ios`.

Note that broadcast has been reported to return `EACCES` on some recent iOS
versions *even with* the entitlement granted, which is another reason the unicast
path is the primary one rather than a fallback.
