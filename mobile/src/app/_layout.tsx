import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useColorScheme } from "react-native";

export default function RootLayout() {
  const scheme = useColorScheme();
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
          options={{ title: "Add a PC", presentation: "modal", headerLargeTitle: false }}
        />
        <Stack.Screen
          name="pair"
          options={{ title: "Pair", presentation: "modal", headerLargeTitle: false }}
        />
        <Stack.Screen
          name="scan"
          options={{
            title: "Scan QR code",
            presentation: "fullScreenModal",
            headerLargeTitle: false,
          }}
        />
        <Stack.Screen name="pc/[id]" options={{ title: "", headerLargeTitle: false }} />
      </Stack>
    </ThemeProvider>
  );
}
