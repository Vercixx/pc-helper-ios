/**
 * The SwiftUI host every screen sits in.
 *
 * `useViewportSizeMeasurement` is what lets a SwiftUI `Form` or `List` fill the
 * screen. Without it the host proposes its content's own ideal size, and a
 * scrolling container has no ideal height -- the screen comes up empty.
 *
 * The stack still owns the header and the safe area, so the host gets the
 * already-inset frame and SwiftUI does its own thing inside that.
 */

import { Host } from "@expo/ui/swift-ui";
import type { ReactNode } from "react";
import { StyleSheet } from "react-native";

export function Screen({ children }: { children: ReactNode }) {
  return (
    <Host style={styles.host} useViewportSizeMeasurement>
      {children}
    </Host>
  );
}

const styles = StyleSheet.create({
  host: { flex: 1 },
});
