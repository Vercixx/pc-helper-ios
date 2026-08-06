/**
 * A navigation-bar button: one SF Symbol, one tap target.
 *
 * The three of these used to be hand-picked text glyphs -- "⚙︎", "＋", "✕" --
 * at three different font sizes, which is how the gear ended up visibly smaller
 * than the plus beside it. Their sizes were guesses at what a symbol looks like,
 * because at the time an SF Symbol could not be drawn: symbol codepoints live in
 * a font that is not in the text fallback chain, so a `<Text>` renders them as a
 * missing-glyph box. `expo-symbols` draws the real thing, and Apple's own
 * optical sizing means one `size` here covers every button.
 *
 * Still a symbol rather than a word, though. iOS 26 wraps a custom header view
 * in a Liquid Glass container sized from the native bar button item's default
 * metrics, not from what React Native measured, so a text label spills straight
 * out of the capsule. A square glyph fits the circle the system draws.
 */

import { SymbolView, type SFSymbol } from "expo-symbols";
import { Pressable, StyleSheet } from "react-native";

import { colors } from "./theme";

/** Matches the metrics UIKit uses for a system bar button item. */
const SYMBOL_SIZE = 22;

export function HeaderButton({
  symbol,
  label,
  onPress,
}: {
  symbol: SFSymbol;
  /** Spoken by VoiceOver: a symbol has no text for it to read. */
  label: string;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      hitSlop={12}
      style={styles.button}
      onPress={onPress}
    >
      <SymbolView
        name={symbol}
        size={SYMBOL_SIZE}
        weight="medium"
        tintColor={colors.tint}
      />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  // Explicit, so the layout does not depend on how the symbol happens to measure.
  button: { width: 30, height: 30, alignItems: "center", justifyContent: "center" },
});
