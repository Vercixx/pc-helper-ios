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

import {
  appGroups,
  bundleIdentifier,
  entitlementKeys,
  hasProvisioningProfile,
  sharedAppGroup,
} from "@modules/app-group";

import { usePCActions } from "@/actions/usePCActions";
import { useLocale, useT, type MessageKey } from "@/i18n";
import { usePCStore } from "@/state/store";
import { isWidgetStorageWorking } from "@/state/widgetBridge";
import { colors, spacing, styles as shared } from "@/ui/theme";

export default function PCDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const t = useT();
  const locale = useLocale();

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
        <Text style={shared.body}>{t("detail.gone")}</Text>
      </View>
    );
  }

  const confirmUnpair = () =>
    Alert.alert(
      t("detail.unpair.title", { name: pc.name }),
      t("detail.unpair.body"),
      [
        { text: t("common.cancel"), style: "cancel" },
        {
          text: t("detail.unpair.confirm"),
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
            <Text style={shared.body}>{headline(status, busy, t)}</Text>
            {busy === "status" ? <ActivityIndicator size="small" /> : null}
          </View>
          {status?.error ? <Text style={shared.caption}>{status.error}</Text> : null}
          {status?.sessionId ? (
            <Text style={shared.caption}>
              {t("detail.session", { id: status.sessionId })}
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
            label={busy === "wake" ? t("status.waking") : t("action.wake")}
            disabled={!canWake || busy !== null}
            onPress={() => void wake()}
          />
          <ActionButton
            label={busy === "unlock" ? t("status.unlocking") : t("action.unlock")}
            disabled={!canUnlock || busy !== null}
            onPress={() => void unlock()}
          />
          <ActionButton
            label={t("action.refresh")}
            secondary
            disabled={busy !== null}
            onPress={() => void refresh()}
          />
        </View>

        <View style={shared.card}>
          <Detail label={t("detail.address")} value={`${pc.hostname}:${pc.port}`} />
          {pc.lastIp ? <Detail label={t("detail.lastIp")} value={pc.lastIp} /> : null}
          <Detail
            label={t("detail.capabilities")}
            value={pc.capabilities.join(", ") || t("common.none")}
          />
          <Detail
            label={t("detail.wakeTargets")}
            value={pc.wake.macs.length > 0 ? pc.wake.macs.join("\n") : t("detail.noTargets")}
          />
          <Detail
            label={t("detail.unlockConfirmation")}
            value={
              pc.requireBiometricsForUnlock === false
                ? t("detail.confirmNone")
                : t("detail.confirmBiometric")
            }
          />
          <Detail label={t("detail.deviceId")} value={pc.deviceId} mono />
          <Detail label={t("detail.fingerprint")} value={pc.serverFp} mono />
          <Detail
            label={t("detail.pairedAt")}
            value={new Date(pc.pairedAt).toLocaleString(locale)}
          />
          {/* Whether widgets can work at all on this install. A re-signing tool
              rewrites the App Group, so what matters is the identifier granted
              at runtime, not the one in app.json. */}
          <Detail label={t("detail.widgetStorage")} value={widgetStorageSummary(t)} mono />
        </View>

        <Pressable style={[shared.card, local.destructive]} onPress={confirmUnpair}>
          <Text style={{ color: colors.red, fontSize: 17 }}>{t("detail.unpair")}</Text>
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

/**
 * Whether shared storage is live, and if not, why not.
 *
 * "No App Group" alone is ambiguous: the profile may genuinely lack one, or it
 * may never have been read. Printing the entitlement keys settles it -- keys
 * present means the profile parsed and the group really was stripped, which is
 * a signing-side fact no code change can undo.
 */
function widgetStorageSummary(t: (key: MessageKey, params?: Record<string, string>) => string) {
  const granted = appGroups();
  if (granted.length > 0) {
    const chosen = sharedAppGroup() ?? granted[0]!;
    return `${isWidgetStorageWorking() ? t("widget.ok") : t("widget.notWritable")}\n${chosen}`;
  }

  const keys = entitlementKeys();
  if (keys.length > 0) {
    return `${t("widget.noGroup")}\n${t("widget.grants", { keys: keys.join(", ") })}`;
  }
  const bundle = bundleIdentifier() ?? "?";
  return hasProvisioningProfile()
    ? `${t("widget.unreadable")}\n${bundle}`
    : `${t("widget.noProfile")}\n${bundle}`;
}

function dotColor(reachable: boolean | undefined, locked: boolean | null | undefined): string {
  if (reachable === undefined) return "#8E8E93";
  if (!reachable) return "#8E8E93";
  return locked ? "#FF9F0A" : "#30D158";
}

function headline(
  status: { reachable: boolean; locked: boolean | null } | undefined,
  busy: string | null,
  t: (key: MessageKey) => string,
): string {
  if (busy === "wake") return t("status.waking");
  if (busy === "unlock") return t("status.unlocking");
  if (!status) return t("status.checking");
  if (!status.reachable) return t("status.asleep");
  if (status.locked === null) return t("status.noUser");
  return status.locked ? t("status.locked") : t("status.unlocked");
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
