/**
 * Design tokens.
 *
 * Most of the app is SwiftUI now, so most of what used to live here — cards,
 * primary buttons, a type scale — has gone: those existed to imitate native
 * chrome that the system draws itself. What is left is the two React Native
 * survivors (the header glyph buttons and the scanner overlay) and the values
 * the SwiftUI side needs as plain strings.
 */

import { foregroundStyle } from "@expo/ui/swift-ui/modifiers";
import { StyleSheet } from "react-native";
import { PlatformColor } from "react-native";

/**
 * Semantic colours, resolved by the system so the app follows light/dark mode
 * and accessibility contrast settings without a manual theme switch.
 */
export const colors = {
  label: PlatformColor("label"),
  secondaryLabel: PlatformColor("secondaryLabel"),
  background: PlatformColor("systemBackground"),
  groupedBackground: PlatformColor("systemGroupedBackground"),
  separator: PlatformColor("separator"),
  tint: PlatformColor("systemBlue"),
  green: PlatformColor("systemGreen"),
  red: PlatformColor("systemRed"),
} as const;

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;

/**
 * Status colours.
 *
 * `PlatformColor`, not the colour *names* `@expo/ui` advertises. Those names
 * are a trap: the bridge tries expo-modules' `UIColor` convertible first, and
 * its table is the CSS3/SVG palette, so `"blue"` is #0000FF and `"green"` is
 * #008000 -- web colours, fixed, and nothing like the system ones. SwiftUI's
 * own palette is only reached by names CSS happens not to define (`primary`,
 * `secondary`, `clear`, `mint`). A `PlatformColor` arrives as
 * `{semantic: ["systemGreen"]}`, which the same convertible resolves against
 * `UIColor`, so it is the real, appearance-adaptive system colour.
 */
export const statusColors = {
  /** Unknown, unreachable, or asleep. */
  unknown: PlatformColor("systemGray"),
  locked: PlatformColor("systemOrange"),
  unlocked: PlatformColor("systemGreen"),
} as const;

/**
 * De-emphasised text on the SwiftUI side.
 *
 * `foregroundStyle("tertiary")` looks like it should work and does not: a bare
 * string is decoded as a `Color`, and expo-modules' colour table knows
 * `primary` and `secondary` but has no `tertiary` and no `tint`, so the
 * modifier is thrown away. The object form routes to SwiftUI's hierarchical
 * styles, which is what these are anyway.
 */
export const secondaryText = foregroundStyle({ type: "hierarchical", style: "secondary" });
export const tertiaryText = foregroundStyle({ type: "hierarchical", style: "tertiary" });

export const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.groupedBackground,
  },
});
