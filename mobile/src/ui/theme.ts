import { Platform, StyleSheet } from "react-native";
import { PlatformColor } from "react-native";

/**
 * Semantic colours, resolved by the system so the app follows light/dark mode
 * and accessibility contrast settings without a manual theme switch.
 */
export const colors = {
  label: PlatformColor("label"),
  secondaryLabel: PlatformColor("secondaryLabel"),
  tertiaryLabel: PlatformColor("tertiaryLabel"),
  background: PlatformColor("systemBackground"),
  groupedBackground: PlatformColor("systemGroupedBackground"),
  card: PlatformColor("secondarySystemGroupedBackground"),
  separator: PlatformColor("separator"),
  tint: PlatformColor("systemBlue"),
  green: PlatformColor("systemGreen"),
  orange: PlatformColor("systemOrange"),
  red: PlatformColor("systemRed"),
} as const;

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;

export const radius = { sm: 8, md: 12, lg: 16 } as const;

export const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.groupedBackground,
  },
  centered: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.xl,
    gap: spacing.md,
  },
  card: {
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  title: {
    fontSize: 22,
    fontWeight: "700",
    color: colors.label,
  },
  body: {
    fontSize: 16,
    color: colors.label,
  },
  caption: {
    fontSize: 13,
    color: colors.secondaryLabel,
  },
  mono: {
    fontFamily: Platform.select({ ios: "Menlo", default: "monospace" }),
    fontSize: 12,
    color: colors.secondaryLabel,
  },
  primaryButton: {
    backgroundColor: colors.tint,
    borderRadius: radius.md,
    paddingVertical: 14,
    alignItems: "center",
  },
  primaryButtonLabel: {
    color: "#fff",
    fontSize: 17,
    fontWeight: "600",
  },
});
