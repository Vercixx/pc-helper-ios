/**
 * QR scanner.
 *
 * The code carries host, port, fingerprint and the one-time pairing code, so a
 * successful scan can go straight to enrollment without the user typing
 * anything.
 *
 * The only screen still built out of React Native views: `CameraView` is an RN
 * view, and there is nothing to gain from hosting it inside SwiftUI. The
 * permission prompt, which has no camera in it, is native like everything else.
 */

import { Button, ContentUnavailableView, VStack } from "@expo/ui/swift-ui";
import { buttonBorderShape, buttonStyle, controlSize } from "@expo/ui/swift-ui/modifiers";
import { CameraView, useCameraPermissions } from "expo-camera";
import { GlassView } from "expo-glass-effect";
import { Stack, useRouter } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { parsePairingTicket } from "@/actions/pair";
import { useT } from "@/i18n";
import { Screen } from "@/ui/Screen";
import { spacing, styles as shared } from "@/ui/theme";

export default function ScanScreen() {
  const [permission, requestPermission] = useCameraPermissions();
  const router = useRouter();
  const t = useT();
  const [problem, setProblem] = useState<string | null>(null);
  // The camera fires repeatedly for the same code; latch so navigation happens
  // exactly once.
  const handled = useRef(false);

  const onScanned = useCallback(
    ({ data }: { data: string }) => {
      if (handled.current) return;

      const ticket = parsePairingTicket(data);
      if (!ticket) {
        setProblem(t("scan.notATicket"));
        return;
      }

      handled.current = true;
      router.replace({
        pathname: "/pair",
        params: {
          host: ticket.host,
          port: String(ticket.port),
          fp: ticket.fingerprint,
          name: ticket.name,
          code: ticket.code ?? "",
          instance: ticket.host.replace(/\.local$/, ""),
          macs: ticket.macs.join(","),
          broadcast: ticket.broadcast ?? "",
        },
      });
    },
    [router, t],
  );

  if (!permission) {
    return <View style={shared.screen} />;
  }

  if (!permission.granted) {
    return (
      <>
        <Stack.Screen options={{ title: t("nav.camera") }} />
        <Screen>
          <VStack spacing={20}>
            <ContentUnavailableView
              title={t("scan.permission.title")}
              systemImage="camera.fill"
              description={t("scan.permission.body")}
            />
            <Button
              label={t("scan.permission.allow")}
              onPress={requestPermission}
              modifiers={[
                buttonStyle("glassProminent"),
                buttonBorderShape("capsule"),
                controlSize("large"),
              ]}
            />
          </VStack>
        </Screen>
      </>
    );
  }

  return (
    <>
      <Stack.Screen options={{ title: t("nav.scan") }} />
      <View style={local.fill}>
        <CameraView
          style={StyleSheet.absoluteFill}
          facing="back"
          barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
          onBarcodeScanned={onScanned}
        />
        <View style={local.overlay} pointerEvents="none">
          {/* Left as a plain stroke rather than glass. Glass is a fill, and the
              one thing that must stay unobstructed is the square the user is
              aiming at -- Apple's own code scanner draws a stroke here too. */}
          <View style={local.reticle} />
          {/* The hint, however, is exactly what glass is for: legible over a
              moving camera feed without a slab of opaque colour. `dark` is
              pinned because the backdrop is a camera feed, not the app's
              background, so the system appearance says nothing useful here. */}
          <GlassView style={local.hintPill} glassEffectStyle="regular" colorScheme="dark">
            <Text style={local.hint}>{problem ?? t("scan.hint")}</Text>
          </GlassView>
        </View>
      </View>
    </>
  );
}

const local = StyleSheet.create({
  fill: { flex: 1, backgroundColor: "#000" },
  overlay: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    alignItems: "center",
    justifyContent: "center",
  },
  reticle: {
    width: 260,
    height: 260,
    borderRadius: 24,
    borderWidth: 3,
    borderColor: "rgba(255,255,255,0.9)",
  },
  hintPill: {
    marginTop: spacing.xl,
    marginHorizontal: spacing.xl,
    borderRadius: 22,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    overflow: "hidden",
  },
  hint: {
    color: "#fff",
    fontSize: 15,
    textAlign: "center",
  },
});
