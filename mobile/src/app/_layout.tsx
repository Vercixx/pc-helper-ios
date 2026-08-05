import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";

export default function RootLayout() {
  return (
    <>
      <StatusBar style="auto" />
      <Stack
        screenOptions={{
          headerLargeTitle: true,
          headerTransparent: false,
        }}
      >
        <Stack.Screen name="index" options={{ title: "My PCs" }} />
        <Stack.Screen
          name="discover"
          options={{ title: "Add a PC", presentation: "modal" }}
        />
        <Stack.Screen
          name="pair"
          options={{ title: "Pair", presentation: "modal" }}
        />
        <Stack.Screen
          name="scan"
          options={{ title: "Scan QR code", presentation: "fullScreenModal" }}
        />
        <Stack.Screen name="pc/[id]" options={{ title: "" }} />
      </Stack>
    </>
  );
}
