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
} as const;

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;

/**
 * Status colours for the SwiftUI side.
 *
 * These cannot come from `colors` above: SwiftUI's `Image color` prop takes a
 * plain string, not a `PlatformColor`. They are SwiftUI's own named colours
 * rather than hex literals because SwiftUI resolves those per appearance -- the
 * hexes that used to live inline in the list and detail screens were the *dark*
 * variants of systemOrange and systemGreen, and stayed dark in light mode.
 */
export const statusColors = {
  /** Unknown, unreachable, or asleep. */
  unknown: "gray",
  locked: "orange",
  unlocked: "green",
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

/**
 * The accent. `"blue"` is `Color.blue`, which is systemBlue and adapts to the
 * appearance -- the same colour `colors.tint` resolves to on the React Native
 * side, and the one the widget already uses.
 */
export const accent = "blue";

export const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.groupedBackground,
  },
});
