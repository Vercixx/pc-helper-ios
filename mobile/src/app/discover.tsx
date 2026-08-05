/**
 * "＋" sheet: PCs found on the network via mDNS, plus the QR fallback.
 *
 * What is shown here is untrusted. It decides what to display and which address
 * to try first; identity is only established when pairing verifies the
 * fingerprint against the one in the code the user scans or types.
 */

import { Stack, useRouter } from "expo-router";
import { useMemo } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { useDiscovery, type DiscoveredPC } from "@/discovery/useDiscovery";
import { splitAround, useT } from "@/i18n";
import { usePCStore } from "@/state/store";
import { colors, spacing, styles as shared } from "@/ui/theme";

export default function DiscoverScreen() {
  const router = useRouter();
  const { available, services, state, error } = useDiscovery(true);
  const pcs = usePCStore((store) => store.pcs);
  const t = useT();
  const [scanBefore, scanAfter] = splitAround(t("discover.scan.body"), "cmd");

  const pairedFingerprints = useMemo(
    () => new Set(pcs.map((pc) => pc.serverFp)),
    [pcs],
  );

  return (
    <>
      <Stack.Screen options={{ title: t("nav.addPC") }} />
      <ScrollView style={shared.screen} contentContainerStyle={local.content}>
        {/* Plain Pressables rather than <Link asChild>: asChild clones the
            child with the Link's own props, which clobbers an array `style`
            and silently drops the card background. */}
        <Pressable
          style={[shared.card, local.primaryCard]}
          accessibilityRole="button"
          onPress={() => router.push("/scan")}
        >
          <Text style={local.cardGlyph}>📷</Text>
          <View style={local.grow}>
            <Text style={shared.body}>{t("discover.scan.title")}</Text>
            <Text style={shared.caption}>
              {scanBefore}
              <Text style={shared.mono}>wol-unlockctl pair</Text>
              {scanAfter}
            </Text>
          </View>
        </Pressable>

        <Pressable
          style={shared.card}
          accessibilityRole="button"
          onPress={() => router.push("/pair")}
        >
          <Text style={shared.body}>{t("discover.manual.title")}</Text>
          <Text style={shared.caption}>{t("discover.manual.body")}</Text>
        </Pressable>

        <Text style={local.sectionHeader}>{t("discover.section")}</Text>

        {!available ? (
          <View style={shared.card}>
            <Text style={shared.body}>{t("discover.unavailable.title")}</Text>
            <Text style={shared.caption}>{error ?? t("discover.unavailable.body")}</Text>
          </View>
        ) : services.length === 0 ? (
          <View style={[shared.card, local.searching]}>
            {state === "failed" ? null : <ActivityIndicator />}
            <View style={local.grow}>
              <Text style={shared.body}>
                {state === "failed" ? t("discover.failed") : t("discover.looking")}
              </Text>
              {error ? <Text style={shared.caption}>{error}</Text> : null}
            </View>
          </View>
        ) : (
          services.map((service) => (
            <DiscoveredRow
              key={service.instanceName}
              service={service}
              alreadyPaired={pairedFingerprints.has(service.fingerprint)}
              onPress={() =>
                router.push({
                  pathname: "/pair",
                  params: {
                    host: service.hostname,
                    instance: service.instanceName,
                    fp: service.fingerprint,
                    name: service.displayName,
                  },
                })
              }
            />
          ))
        )}

        <Text style={[shared.caption, local.footnote]}>{t("discover.footnote")}</Text>
      </ScrollView>
    </>
  );
}

function DiscoveredRow({
  service,
  alreadyPaired,
  onPress,
}: {
  service: DiscoveredPC;
  alreadyPaired: boolean;
  onPress: () => void;
}) {
  const t = useT();
  return (
    <Pressable
      style={shared.card}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={
        alreadyPaired
          ? t("discover.a11y.alreadyPaired", { name: service.displayName })
          : service.displayName
      }
    >
      <View style={local.rowTop}>
        <Text style={shared.body}>{service.displayName}</Text>
        {alreadyPaired ? (
          <Text style={[shared.caption, { color: colors.green }]}>{t("discover.paired")}</Text>
        ) : service.pairingOpen ? (
          <Text style={[shared.caption, { color: colors.tint }]}>
            {t("discover.pairingOpen")}
          </Text>
        ) : null}
      </View>
      <Text style={shared.caption}>{service.hostname}</Text>
      {service.fingerprint ? (
        <Text style={shared.mono}>{service.fingerprint.slice(0, 24)}…</Text>
      ) : null}
      {service.capabilities.length > 0 ? (
        <Text style={shared.caption}>{service.capabilities.join(" · ")}</Text>
      ) : null}
    </Pressable>
  );
}

const local = StyleSheet.create({
  content: { padding: spacing.lg, gap: spacing.md },
  primaryCard: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  cardGlyph: { fontSize: 28, color: colors.tint },
  grow: { flex: 1, gap: 2 },
  searching: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  sectionHeader: {
    fontSize: 13,
    color: colors.secondaryLabel,
    marginTop: spacing.md,
    marginLeft: spacing.xs,
    letterSpacing: 0.5,
  },
  rowTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  footnote: { marginTop: spacing.md, textAlign: "center" },
});
