/**
 * The leading close button for a modally presented screen.
 *
 * A sheet gets no back button from the navigator, so without this the only way
 * out of "Add a PC", "Pair with a PC" or the scanner is the swipe-down gesture
 * -- which is invisible, and unavailable on the full-screen scanner where the
 * camera view fills the sheet.
 *
 * It is a glyph rather than the word "Cancel" on purpose. iOS 26 wraps a custom
 * header view in a Liquid Glass container sized from the native bar button
 * item's default metrics, not from what React Native measured, so a text label
 * spills straight out of the capsule. A single glyph fits the circle the system
 * draws -- the same reason the "＋" on the list screen looks right.
 */

import { useRouter } from "expo-router";
import { Pressable, StyleSheet, Text } from "react-native";

import { colors } from "./theme";

export function ModalCloseButton({ label = "Cancel" }: { label?: string }) {
  const router = useRouter();

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      hitSlop={12}
      style={styles.button}
      // `back()` returns to whatever presented this sheet -- the list, or the
      // discovery sheet underneath a pairing screen. The fallback covers being
      // deep-linked straight into a modal, where there is no history to pop.
      onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))}
    >
      {/* U+2715, not an SF Symbol codepoint: symbol glyphs live in a font that
          is not in the text fallback chain and render as a missing-glyph box. */}
      <Text style={styles.glyph}>✕</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  // Explicit, so the layout does not depend on how the glyph happens to measure.
  button: { width: 30, height: 30, alignItems: "center", justifyContent: "center" },
  glyph: { fontSize: 19, fontWeight: "600", color: colors.tint, lineHeight: 24 },
});
