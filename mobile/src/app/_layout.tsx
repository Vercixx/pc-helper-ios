import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { useColorScheme } from "react-native";

import { useT } from "@/i18n";
import { startWidgetSync } from "@/state/widgetBridge";
import { ModalCloseButton } from "@/ui/ModalCloseButton";

/** Sheets need an explicit way out; the navigator gives them no back button. */
const dismissable = { headerLeft: () => <ModalCloseButton /> };

export default function RootLayout() {
  const scheme = useColorScheme();
  // Titles are read here rather than left to each screen, so switching language
  // re-renders the whole navigator at once instead of one screen at a time.
  const t = useT();

  // The widget extension only sees what the app writes into the App Group.
  useEffect(() => startWidgetSync(), []);

  // Without this the navigation header keeps React Navigation's light theme
  // while the screens use PlatformColor and follow the system — which reads as
  // a white header stapled onto a black app.
  const isDark = scheme === "dark";

  return (
    <ThemeProvider value={isDark ? DarkTheme : DefaultTheme}>
      <StatusBar style={isDark ? "light" : "dark"} />
      <Stack screenOptions={{ headerLargeTitle: true }}>
        <Stack.Screen name="index" options={{ title: t("nav.myPCs") }} />
        <Stack.Screen
          name="discover"
          options={{
            title: t("nav.addPC"),
            presentation: "modal",
            headerLargeTitle: false,
            ...dismissable,
          }}
        />
        <Stack.Screen
          name="pair"
          options={{
            title: t("nav.pair"),
            presentation: "modal",
            headerLargeTitle: false,
            ...dismissable,
          }}
        />
        <Stack.Screen
          name="scan"
          options={{
            title: t("nav.scan"),
            presentation: "fullScreenModal",
            headerLargeTitle: false,
            ...dismissable,
          }}
        />
        <Stack.Screen
          name="settings"
          options={{
            title: t("nav.settings"),
            presentation: "modal",
            headerLargeTitle: false,
            ...dismissable,
          }}
        />
        <Stack.Screen name="pc/[id]" options={{ title: "", headerLargeTitle: false }} />
      </Stack>
    </ThemeProvider>
  );
}
