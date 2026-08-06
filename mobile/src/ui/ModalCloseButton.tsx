/**
 * The leading close button for a modally presented screen.
 *
 * A sheet gets no back button from the navigator, so without this the only way
 * out of "Add a PC", "Pair with a PC" or the scanner is the swipe-down gesture
 * -- which is invisible, and unavailable on the full-screen scanner where the
 * camera view fills the sheet.
 *
 * See `HeaderButton` for why this is a symbol and not the word "Cancel".
 */

import { useRouter } from "expo-router";

import { useT } from "@/i18n";

import { HeaderButton } from "./HeaderButton";

export function ModalCloseButton({ label }: { label?: string }) {
  const router = useRouter();
  const t = useT();

  return (
    <HeaderButton
      symbol="xmark"
      label={label ?? t("common.cancel")}
      // `back()` returns to whatever presented this sheet -- the list, or the
      // discovery sheet underneath a pairing screen. The fallback covers being
      // deep-linked straight into a modal, where there is no history to pop.
      onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))}
    />
  );
}
