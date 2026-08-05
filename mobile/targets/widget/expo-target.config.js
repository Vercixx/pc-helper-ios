/**
 * WidgetKit extension target.
 *
 * The App Group is mirrored from the app's own entitlements rather than
 * repeated: the two must match exactly or the extension reads an empty
 * container and every widget renders "Not paired".
 *
 * @type {import("@bacons/apple-targets/build/config").ConfigFunction}
 */
module.exports = (config) => ({
  type: "widget",
  name: "PCUnlockWidget",
  displayName: "PC Unlock",
  bundleIdentifier: ".widget",
  // ControlWidget (Control Center / Lock Screen buttons) is iOS 18+.
  deploymentTarget: "18.0",
  frameworks: ["SwiftUI", "WidgetKit", "AppIntents"],
  entitlements: {
    "com.apple.security.application-groups":
      config.ios?.entitlements?.["com.apple.security.application-groups"] ?? [],
  },
  colors: {
    $accent: { color: "#0A84FF", darkColor: "#0A84FF" },
  },
});
