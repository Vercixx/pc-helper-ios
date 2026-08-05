/**
 * "＋" sheet: PCs found on the network via mDNS, plus the QR fallback.
 *
 * What is shown here is untrusted. It decides what to display and which address
 * to try first; identity is only established when pairing verifies the
 * fingerprint against the one in the code the user scans or types.
 */

import { Link, Stack, useRouter } from "expo-router";
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
import { usePCStore } from "@/state/store";
import { colors, spacing, styles as shared } from "@/ui/theme";

export default function DiscoverScreen() {
  const router = useRouter();
  const { available, services, state, error } = useDiscovery(true);
  const pcs = usePCStore((store) => store.pcs);

  const pairedFingerprints = useMemo(
    () => new Set(pcs.map((pc) => pc.serverFp)),
    [pcs],
  );

  return (
    <>
      <Stack.Screen options={{ title: "Add a PC" }} />
      <ScrollView style={shared.screen} contentContainerStyle={local.content}>
        <Link href="/scan" asChild>
          <Pressable style={[shared.card, local.primaryCard]}>
            <Text style={local.cardGlyph}>􀎼</Text>
            <View style={local.grow}>
              <Text style={shared.body}>Scan QR code</Text>
              <Text style={shared.caption}>
                The fastest way. Run <Text style={shared.mono}>wol-unlockctl pair</Text> on
                the PC.
              </Text>
            </View>
          </Pressable>
        </Link>

        <Link href={{ pathname: "/pair", params: {} }} asChild>
          <Pressable style={shared.card}>
            <Text style={shared.body}>Enter details manually</Text>
            <Text style={shared.caption}>
              If the PC is on another subnet or discovery is blocked.
            </Text>
          </Pressable>
        </Link>

        <Text style={local.sectionHeader}>ON THIS NETWORK</Text>

        {!available ? (
          <View style={shared.card}>
            <Text style={shared.body}>Discovery unavailable</Text>
            <Text style={shared.caption}>
              {error ??
                "Bonjour browsing needs a development build. Use the QR code instead."}
            </Text>
          </View>
        ) : services.length === 0 ? (
          <View style={[shared.card, local.searching]}>
            {state === "failed" ? null : <ActivityIndicator />}
            <View style={local.grow}>
              <Text style={shared.body}>
                {state === "failed" ? "Couldn't browse the network" : "Looking for PCs…"}
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

        <Text style={[shared.caption, local.footnote]}>
          Discovered names and fingerprints are hints only. Pairing checks the PC's
          identity against the code you enter before trusting it.
        </Text>
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
  return (
    <Pressable
      style={shared.card}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`${service.displayName}${alreadyPaired ? ", already paired" : ""}`}
    >
      <View style={local.rowTop}>
        <Text style={shared.body}>{service.displayName}</Text>
        {alreadyPaired ? (
          <Text style={[shared.caption, { color: colors.green }]}>Paired</Text>
        ) : service.pairingOpen ? (
          <Text style={[shared.caption, { color: colors.tint }]}>Pairing open</Text>
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
