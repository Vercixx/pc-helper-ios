import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { useColorScheme } from "react-native";

import { startWidgetSync } from "@/state/widgetBridge";
import { ModalCloseButton } from "@/ui/ModalCloseButton";

/** Sheets need an explicit way out; the navigator gives them no back button. */
const dismissable = { headerLeft: () => <ModalCloseButton /> };

export default function RootLayout() {
  const scheme = useColorScheme();

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
        <Stack.Screen name="index" options={{ title: "My PCs" }} />
        <Stack.Screen
          name="discover"
          options={{
            title: "Add a PC",
            presentation: "modal",
            headerLargeTitle: false,
            ...dismissable,
          }}
        />
        <Stack.Screen
          name="pair"
          options={{
            title: "Pair",
            presentation: "modal",
            headerLargeTitle: false,
            ...dismissable,
          }}
        />
        <Stack.Screen
          name="scan"
          options={{
            title: "Scan QR code",
            presentation: "fullScreenModal",
            headerLargeTitle: false,
            ...dismissable,
          }}
        />
        <Stack.Screen name="pc/[id]" options={{ title: "", headerLargeTitle: false }} />
      </Stack>
    </ThemeProvider>
  );
}
