/**
 * The leading "Cancel" button for a modally presented screen.
 *
 * A sheet gets no back button from the navigator, so without this the only way
 * out of "Add a PC", "Pair with a PC" or the scanner is the swipe-down gesture
 * -- which is invisible, and impossible on the full-screen scanner where the
 * camera view fills the sheet.
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
      // `back()` returns to whatever presented this sheet -- the list, or the
      // discovery sheet underneath a pairing screen. The fallback covers being
      // deep-linked straight into a modal, where there is no history to pop.
      onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))}
    >
      <Text style={styles.label}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  label: { fontSize: 17, color: colors.tint },
});
