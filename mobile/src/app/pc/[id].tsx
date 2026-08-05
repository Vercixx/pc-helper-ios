/**
 * Detail screen: status, the two actions as full-width buttons, and unpairing.
 */

import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { usePCActions } from "@/actions/usePCActions";
import { usePCStore } from "@/state/store";
import { colors, spacing, styles as shared } from "@/ui/theme";

export default function PCDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();

  const pc = usePCStore(useCallback((state) => state.pcs.find((item) => item.id === id), [id]));
  const status = usePCStore(useCallback((state) => (id ? state.statuses[id] : undefined), [id]));
  const removePC = usePCStore((state) => state.removePC);

  const { busy, feedback, refresh, wake, unlock } = usePCActions(pc);

  // Once, on entry. `refresh` keeps a stable identity for as long as this PC is
  // the one on screen, so this is a mount effect and not a poll loop.
  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (!pc) {
    return (
      <View style={shared.centered}>
        <Text style={shared.body}>This PC is no longer paired.</Text>
      </View>
    );
  }

  const confirmUnpair = () =>
    Alert.alert(
      `Unpair ${pc.name}?`,
      "This phone's key will be deleted. The PC will keep its record until you revoke it there with 'wol-unlockctl revoke'.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Unpair",
          style: "destructive",
          onPress: async () => {
            await removePC(pc.id);
            // `dismissTo`, not `replace`: the list is already at the bottom of
            // this stack, and replacing pushes a *second* copy of it -- which
            // is why the list came back wearing a "‹ My PCs" button pointing at
            // itself. This pops back to the one that is already there.
            router.dismissTo("/");
          },
        },
      ],
    );

  const canWake = pc.wake.macs.length > 0;
  const canUnlock = pc.capabilities.includes("unlock");

  return (
    <>
      <Stack.Screen options={{ title: pc.name }} />
      <ScrollView style={shared.screen} contentContainerStyle={local.content}>
        <View style={shared.card}>
          <View style={local.statusRow}>
            <View style={[local.dot, { backgroundColor: dotColor(status?.reachable, status?.locked) }]} />
            <Text style={shared.body}>{headline(status, busy)}</Text>
            {busy === "status" ? <ActivityIndicator size="small" /> : null}
          </View>
          {status?.error ? <Text style={shared.caption}>{status.error}</Text> : null}
          {status?.sessionId ? (
            <Text style={shared.caption}>
              Session {status.sessionId}
              {status.desktop ? ` · ${status.desktop}` : ""}
            </Text>
          ) : null}
        </View>

        {feedback ? (
          <View style={shared.card}>
            <Text
              style={
                feedback.tone === "error"
                  ? { color: colors.red }
                  : feedback.tone === "success"
                    ? { color: colors.green }
                    : shared.body
              }
            >
              {feedback.message}
            </Text>
          </View>
        ) : null}

        <View style={local.actions}>
          <ActionButton
            label={busy === "wake" ? "Waking…" : "Wake up"}
            disabled={!canWake || busy !== null}
            onPress={() => void wake()}
          />
          <ActionButton
            label={busy === "unlock" ? "Unlocking…" : "Unlock session"}
            disabled={!canUnlock || busy !== null}
            onPress={() => void unlock()}
          />
          <ActionButton
            label="Refresh"
            secondary
            disabled={busy !== null}
            onPress={() => void refresh()}
          />
        </View>

        <View style={shared.card}>
          <Detail label="Address" value={`${pc.hostname}:${pc.port}`} />
          {pc.lastIp ? <Detail label="Last IP" value={pc.lastIp} /> : null}
          <Detail label="Capabilities" value={pc.capabilities.join(", ") || "none"} />
          <Detail
            label="Wake targets"
            value={pc.wake.macs.length > 0 ? pc.wake.macs.join("\n") : "none configured"}
          />
          <Detail
            label="Unlock confirmation"
            value={pc.requireBiometricsForUnlock === false ? "None" : "Face ID / passcode"}
          />
          <Detail label="This device's ID" value={pc.deviceId} mono />
          <Detail label="PC fingerprint" value={pc.serverFp} mono />
          <Detail label="Paired" value={new Date(pc.pairedAt).toLocaleString()} />
        </View>

        <Pressable style={[shared.card, local.destructive]} onPress={confirmUnpair}>
          <Text style={{ color: colors.red, fontSize: 17 }}>Unpair this PC</Text>
        </Pressable>
      </ScrollView>
    </>
  );
}

function ActionButton({
  label,
  onPress,
  disabled,
  secondary,
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  secondary?: boolean;
}) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityState={{ disabled: Boolean(disabled) }}
      style={[
        shared.primaryButton,
        secondary ? local.secondaryButton : null,
        disabled ? local.disabled : null,
      ]}
    >
      <Text style={[shared.primaryButtonLabel, secondary ? { color: colors.tint } : null]}>
        {label}
      </Text>
    </Pressable>
  );
}

function Detail({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <View style={local.detailRow}>
      <Text style={shared.caption}>{label}</Text>
      <Text style={mono ? shared.mono : shared.body} selectable>
        {value}
      </Text>
    </View>
  );
}

function dotColor(reachable: boolean | undefined, locked: boolean | null | undefined): string {
  if (reachable === undefined) return "#8E8E93";
  if (!reachable) return "#8E8E93";
  return locked ? "#FF9F0A" : "#30D158";
}

function headline(
  status: { reachable: boolean; locked: boolean | null } | undefined,
  busy: string | null,
): string {
  if (busy === "wake") return "Waking…";
  if (busy === "unlock") return "Unlocking…";
  if (!status) return "Checking…";
  if (!status.reachable) return "Asleep or unreachable";
  if (status.locked === null) return "Online — nobody logged in";
  return status.locked ? "Locked" : "Unlocked";
}

const local = StyleSheet.create({
  content: { padding: spacing.lg, gap: spacing.md },
  statusRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  dot: { width: 10, height: 10, borderRadius: 5 },
  actions: { gap: spacing.sm },
  secondaryButton: { backgroundColor: "transparent" },
  disabled: { opacity: 0.4 },
  detailRow: { gap: 2, paddingVertical: 6 },
  destructive: { alignItems: "center" },
});
