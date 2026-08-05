/**
 * QR scanner.
 *
 * The code carries host, port, fingerprint and the one-time pairing code, so a
 * successful scan can go straight to enrollment without the user typing
 * anything.
 */

import { CameraView, useCameraPermissions } from "expo-camera";
import { Stack, useRouter } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { parsePairingTicket } from "@/actions/pair";
import { useT } from "@/i18n";
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
        <View style={shared.centered}>
          <Text style={shared.title}>{t("scan.permission.title")}</Text>
          <Text style={[shared.caption, local.center]}>{t("scan.permission.body")}</Text>
          <Pressable style={[shared.primaryButton, local.stretch]} onPress={requestPermission}>
            <Text style={shared.primaryButtonLabel}>{t("scan.permission.allow")}</Text>
          </Pressable>
        </View>
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
          <View style={local.reticle} />
          <Text style={local.hint}>{problem ?? t("scan.hint")}</Text>
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
  hint: {
    marginTop: spacing.xl,
    color: "#fff",
    fontSize: 15,
    textAlign: "center",
    paddingHorizontal: spacing.xl,
  },
  center: { textAlign: "center" },
  stretch: { alignSelf: "stretch", marginTop: spacing.lg },
});
