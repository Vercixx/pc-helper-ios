/**
 * Detail screen: status, the two actions, and unpairing.
 *
 * The actions sit in a `GlassEffectContainer` so the three capsules blend into
 * one another the way iOS 26 draws a grouped control cluster. Their section has
 * a clear row background -- glass over a form row's own material reads as a
 * smudge, not as glass.
 */

import {
  Button,
  Form,
  HStack,
  Image,
  LabeledContent,
  Namespace,
  Section,
  Spacer,
  Text,
  VStack,
  GlassEffectContainer,
} from "@expo/ui/swift-ui";
import {
  buttonBorderShape,
  buttonStyle,
  controlSize,
  disabled as disabledModifier,
  font,
  foregroundStyle,
  glassEffectId,
  lineLimit,
  listRowBackground,
  symbolEffect,
  textSelection,
} from "@expo/ui/swift-ui/modifiers";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useId } from "react";
import { Alert, type ColorValue } from "react-native";

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
import type { PCStatusSnapshot } from "@/state/types";
import { isWidgetStorageWorking } from "@/state/widgetBridge";
import { Screen } from "@/ui/Screen";
import { statusColor, statusSymbol } from "@/ui/status";
import { colors, secondaryText } from "@/ui/theme";

export default function PCDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const t = useT();
  const locale = useLocale();
  const glassNamespace = useId();

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
      <Screen>
        <VStack>
          <Text>{t("detail.gone")}</Text>
        </VStack>
      </Screen>
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
  const anyBusy = busy !== null;

  return (
    <>
      <Stack.Screen options={{ title: pc.name }} />
      <Screen>
        <Form>
          <Section>
            <HStack spacing={12}>
              <Image
                systemName={statusSymbol(status)}
                size={28}
                color={statusColor(status)}
                // Only while something is in flight: swapping the modifier in
                // and out is what starts and stops the animation, so no
                // observable state has to be bridged for it.
                modifiers={
                  anyBusy
                    ? [symbolEffect({ effect: "pulse" }, { options: { repeat: "continuous" } })]
                    : []
                }
              />
              <VStack alignment="leading" spacing={2}>
                <Text modifiers={[font({ size: 17 })]}>{headline(status, busy, t)}</Text>
                {status?.error ? (
                  <Text modifiers={[font({ size: 13 }), secondaryText]}>
                    {status.error}
                  </Text>
                ) : null}
                {status?.sessionId ? (
                  <Text modifiers={[font({ size: 13 }), secondaryText]}>
                    {t("detail.session", { id: status.sessionId })}
                    {status.desktop ? ` · ${status.desktop}` : ""}
                  </Text>
                ) : null}
              </VStack>
              <Spacer />
            </HStack>
          </Section>

          <Section
            footer={
              feedback ? (
                <Text modifiers={[foregroundStyle(feedbackColor(feedback.tone))]}>
                  {feedback.message}
                </Text>
              ) : undefined
            }
            // `"clear"` is safe where a colour *name* would not be: CSS has no
            // "clear" (it calls it "transparent"), so the string falls past the
            // web palette and reaches SwiftUI's own `.clear`.
            modifiers={[listRowBackground("clear")]}
          >
            {/* Stacked, not side by side. Three of these labels sharing one
                row's width leaves each about a third of it, which is narrower
                than "Unlock session" -- SwiftUI wraps and hyphenates, and a
                capsule drawn around three lines of text is a circle. */}
            <Namespace id={glassNamespace}>
              <GlassEffectContainer spacing={12}>
                <VStack spacing={12}>
                  <ActionButton
                    label={busy === "wake" ? t("status.waking") : t("action.wake")}
                    symbol="power"
                    prominent
                    disabled={!canWake || anyBusy}
                    onPress={() => void wake()}
                    glassId="wake"
                    namespace={glassNamespace}
                  />
                  <ActionButton
                    label={busy === "unlock" ? t("status.unlocking") : t("action.unlock")}
                    symbol="lock.open"
                    disabled={!canUnlock || anyBusy}
                    onPress={() => void unlock()}
                    glassId="unlock"
                    namespace={glassNamespace}
                  />
                  <ActionButton
                    label={t("action.refresh")}
                    symbol="arrow.clockwise"
                    disabled={anyBusy}
                    onPress={() => void refresh()}
                    glassId="refresh"
                    namespace={glassNamespace}
                  />
                </VStack>
              </GlassEffectContainer>
            </Namespace>
          </Section>

          <Section>
            <Detail label={t("detail.address")} value={`${pc.hostname}:${pc.port}`} />
            {pc.lastIp ? <Detail label={t("detail.lastIp")} value={pc.lastIp} /> : null}
            <Detail
              label={t("detail.capabilities")}
              value={pc.capabilities.join(", ") || t("common.none")}
            />
            <Detail
              label={t("detail.unlockConfirmation")}
              value={
                pc.requireBiometricsForUnlock === false
                  ? t("detail.confirmNone")
                  : t("detail.confirmBiometric")
              }
            />
            <Detail
              label={t("detail.pairedAt")}
              value={new Date(pc.pairedAt).toLocaleString(locale)}
            />
            <StackedDetail
              label={t("detail.wakeTargets")}
              value={pc.wake.macs.length > 0 ? pc.wake.macs.join("\n") : t("detail.noTargets")}
              mono={pc.wake.macs.length > 0}
            />
            <StackedDetail label={t("detail.deviceId")} value={pc.deviceId} mono />
            <StackedDetail label={t("detail.fingerprint")} value={pc.serverFp} mono />
            {/* Whether widgets can work at all on this install. A re-signing tool
                rewrites the App Group, so what matters is the identifier granted
                at runtime, not the one in app.json. */}
            <StackedDetail label={t("detail.widgetStorage")} value={widgetStorageSummary(t)} mono />
          </Section>

          <Section>
            <Button role="destructive" label={t("detail.unpair")} onPress={confirmUnpair} />
          </Section>
        </Form>
      </Screen>
    </>
  );
}

/**
 * One of the three glass capsules.
 *
 * The label is built by hand rather than passed as `label` + `systemImage`,
 * which would be the obvious way and does not work: under
 * `.buttonStyle(.glassProminent)` SwiftUI reserves the icon's slot in the
 * `Label` and then draws nothing in it, so the Wake button came out with a
 * blank gap where its power symbol should be while the two plain-glass buttons
 * beside it drew theirs fine. An `Image` placed in the button's content is just
 * a view, and renders.
 *
 * The `Spacer`s either side are what make the capsule span the row. The obvious
 * way there, `frame({ maxWidth: Infinity })`, does not survive the trip into a
 * `CGFloat?` -- the buttons came back sized to their text.
 *
 * Neither the image nor the text sets a colour, so both inherit whatever the
 * button style decides: white on the prominent capsule, the accent on the
 * others.
 */
function ActionButton({
  label,
  symbol,
  onPress,
  disabled,
  prominent,
  glassId,
  namespace,
}: {
  label: string;
  symbol: "power" | "lock.open" | "arrow.clockwise";
  onPress: () => void;
  disabled: boolean;
  prominent?: boolean;
  glassId: string;
  namespace: string;
}) {
  return (
    <Button
      onPress={onPress}
      modifiers={[
        buttonStyle(prominent ? "glassProminent" : "glass"),
        buttonBorderShape("capsule"),
        controlSize("large"),
        glassEffectId(glassId, namespace),
        disabledModifier(disabled),
      ]}
    >
      <HStack spacing={8}>
        <Spacer />
        {/* No `size`: left alone the symbol scales with the button's own font,
            so it stays optically matched to the label at any Dynamic Type. */}
        <Image systemName={symbol} />
        <Text modifiers={[lineLimit(1)]}>{label}</Text>
        <Spacer />
      </HStack>
    </Button>
  );
}

/** A short value, on the same line as its label -- the Form idiom. */
function Detail({ label, value }: { label: string; value: string }) {
  return (
    <LabeledContent label={label}>
      <Text modifiers={[textSelection(true)]}>{value}</Text>
    </LabeledContent>
  );
}

/**
 * A value too long to sit beside its label: fingerprints, device IDs, a list of
 * MACs. Stacked, so it can wrap instead of being truncated to an ellipsis.
 */
function StackedDetail({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <VStack alignment="leading" spacing={2}>
      <Text modifiers={[font({ size: 13 }), secondaryText]}>{label}</Text>
      <Text
        modifiers={[
          font(mono ? { size: 12, design: "monospaced" } : { size: 16 }),
          lineLimit(),
          textSelection(true),
        ]}
      >
        {value}
      </Text>
    </VStack>
  );
}

function feedbackColor(tone: "success" | "error" | "info"): ColorValue {
  if (tone === "error") return colors.red;
  if (tone === "success") return colors.green;
  return colors.secondaryLabel;
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

function headline(
  status: PCStatusSnapshot | undefined,
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
