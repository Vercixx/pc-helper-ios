/**
 * The main screen: linked PCs, each with a native long-press context menu
 * offering "Wake up" and "Unlock session".
 */

import { Button, ContextMenu, HStack, Host, Image, Spacer, Text, VStack } from "@expo/ui/swift-ui";
import { font, foregroundColor, frame, padding } from "@expo/ui/swift-ui/modifiers";
import { Stack, useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text as RNText,
  View,
} from "react-native";

import { usePCActions } from "@/actions/usePCActions";
import { splitAround, useT, type MessageKey } from "@/i18n";
import { usePCStore } from "@/state/store";
import type { LinkedPC, PCStatusSnapshot } from "@/state/types";
import { colors, spacing, styles as shared } from "@/ui/theme";

export default function PCListScreen() {
  const pcs = usePCStore((state) => state.pcs);
  const statuses = usePCStore((state) => state.statuses);
  // Bumped by pull-to-refresh. Rows watch it and re-poll, which is cheaper and
  // less jarring than remounting them.
  const [generation, setGeneration] = useState(0);
  const router = useRouter();
  const t = useT();

  return (
    <>
      <Stack.Screen
        options={{
          title: t("nav.myPCs"),
          headerLeft: () => (
            <Pressable
              accessibilityLabel={t("list.a11y.settings")}
              accessibilityRole="button"
              hitSlop={12}
              onPress={() => router.push("/settings")}
            >
              <RNText style={local.headerGlyph}>⚙︎</RNText>
            </Pressable>
          ),
          headerRight: () => (
            <Pressable
              accessibilityLabel={t("list.a11y.addPC")}
              accessibilityRole="button"
              hitSlop={12}
              onPress={() => router.push("/discover")}
            >
              <RNText style={local.addButton}>＋</RNText>
            </Pressable>
          ),
        }}
      />

      <ScrollView
        style={shared.screen}
        contentInsetAdjustmentBehavior="automatic"
        contentContainerStyle={pcs.length === 0 ? local.emptyContainer : local.list}
        refreshControl={
          <RefreshControl refreshing={false} onRefresh={() => setGeneration((n) => n + 1)} />
        }
      >
        {pcs.length === 0 ? (
          <EmptyState />
        ) : (
          pcs.map((pc) => (
            <PCRow
              key={pc.id}
              pc={pc}
              status={statuses[pc.id]}
              generation={generation}
            />
          ))
        )}
      </ScrollView>
    </>
  );
}

function EmptyState() {
  const router = useRouter();
  const t = useT();
  const [before, after] = splitAround(t("list.empty.body"), "cmd");
  return (
    <View style={shared.centered}>
      <RNText style={local.emptyGlyph}>🖥️</RNText>
      <RNText style={shared.title}>{t("list.empty.title")}</RNText>
      <RNText style={[shared.caption, local.centerText]}>
        {before}
        <RNText style={shared.mono}>wol-unlockctl pair</RNText>
        {after}
      </RNText>
      {/* Not <Link asChild>: it clones the child with its own props, which
          clobbers an array `style` and drops the button's background. */}
      <Pressable
        style={[shared.primaryButton, local.stretch]}
        accessibilityRole="button"
        onPress={() => router.push("/discover")}
      >
        <RNText style={shared.primaryButtonLabel}>{t("nav.addPC")}</RNText>
      </Pressable>
    </View>
  );
}

/**
 * One row.
 *
 * The row is a SwiftUI `ContextMenu`, so a long press produces the real iOS menu
 * with its blur and preview rather than a modal imitation of one.
 */
function PCRow({
  pc,
  status,
  generation,
}: {
  pc: LinkedPC;
  status: PCStatusSnapshot | undefined;
  generation: number;
}) {
  const router = useRouter();
  const t = useT();
  const { busy, feedback, refresh, refreshIfStale, wake, unlock } = usePCActions(pc);

  // Refresh whenever the list comes back into view, so what is shown is never
  // left over from a previous app session. Throttled: returning from the detail
  // screen, which just polled, should not poll again.
  useFocusEffect(
    useCallback(() => {
      refreshIfStale();
    }, [refreshIfStale]),
  );

  // Pull-to-refresh means "I don't believe you", so it bypasses the throttle.
  const seenGeneration = useRef(generation);
  useEffect(() => {
    if (generation === seenGeneration.current) return;
    seenGeneration.current = generation;
    void refresh();
  }, [generation, refresh]);

  const openDetails = useCallback(
    () => router.push({ pathname: "/pc/[id]", params: { id: pc.id } }),
    [router, pc.id],
  );

  const canUnlock = pc.capabilities.includes("unlock");
  const canWake = pc.wake.macs.length > 0;
  const subtitle = describe(pc, status, busy, t);

  return (
    <View style={local.rowWrapper}>
      <Host matchContents>
        <ContextMenu>
          <ContextMenu.Items>
            {canWake ? (
              <Button label={t("action.wake")} systemImage="power" onPress={() => void wake()} />
            ) : null}
            {canUnlock ? (
              <Button
                label={t("action.unlock")}
                systemImage="lock.open"
                onPress={() => void unlock()}
              />
            ) : null}
            <Button
              label={t("action.refresh")}
              systemImage="arrow.clockwise"
              onPress={() => void refresh()}
            />
            <Button label={t("action.details")} systemImage="info.circle" onPress={openDetails} />
          </ContextMenu.Items>

          <ContextMenu.Trigger>
            <HStack spacing={14} modifiers={[frame({ height: 64 }), padding({ horizontal: 16 })]}>
              <Image
                systemName={statusSymbol(status)}
                size={26}
                color={statusColor(status)}
              />
              <VStack alignment="leading" spacing={2}>
                <Text modifiers={[font({ size: 17, weight: "semibold" })]}>{pc.name}</Text>
                <Text modifiers={[font({ size: 13 }), foregroundColor("secondary")]}>
                  {subtitle}
                </Text>
              </VStack>
              <Spacer />
            </HStack>
          </ContextMenu.Trigger>
        </ContextMenu>
      </Host>

      {/* The SwiftUI host owns the long press; this overlay handles the plain
          tap that opens the detail screen. */}
      <Pressable
        style={StyleSheet.absoluteFill}
        accessibilityRole="button"
        accessibilityLabel={`${pc.name}. ${subtitle}`}
        accessibilityHint={t("list.a11y.rowHint")}
        onPress={openDetails}
      />

      {busy ? (
        <View style={local.busyBadge} pointerEvents="none">
          <ActivityIndicator size="small" />
        </View>
      ) : null}

      {feedback ? (
        <RNText
          style={[
            local.feedback,
            feedback.tone === "error" ? { color: colors.red } : null,
            feedback.tone === "success" ? { color: colors.green } : null,
          ]}
        >
          {feedback.message}
        </RNText>
      ) : null}
    </View>
  );
}

function statusSymbol(status: PCStatusSnapshot | undefined) {
  if (!status || !status.reachable) return "moon.zzz.fill" as const;
  return status.locked ? ("lock.fill" as const) : ("desktopcomputer" as const);
}

function statusColor(status: PCStatusSnapshot | undefined): string {
  if (!status || !status.reachable) return "#8E8E93";
  return status.locked ? "#FF9F0A" : "#30D158";
}

function describe(
  pc: LinkedPC,
  status: PCStatusSnapshot | undefined,
  busy: string | null,
  t: (key: MessageKey) => string,
): string {
  if (busy === "wake") return t("status.waking");
  if (busy === "unlock") return t("status.unlocking");
  if (busy === "status") return t("status.checking");
  if (!status) return pc.hostname;
  // `status.error` arrives already translated -- ApiError.friendly does it.
  if (!status.reachable) return status.error ?? t("status.asleep");
  if (status.locked === null) return t("status.noUser");
  return status.locked ? t("status.lockedHint") : t("status.unlocked");
}

const local = StyleSheet.create({
  list: { padding: spacing.lg, gap: spacing.md },
  emptyContainer: { flexGrow: 1 },
  emptyGlyph: { fontSize: 56 },
  centerText: { textAlign: "center" },
  stretch: { alignSelf: "stretch", marginTop: spacing.lg },
  addButton: { fontSize: 28, color: colors.tint, lineHeight: 32 },
  headerGlyph: { fontSize: 20, color: colors.tint, lineHeight: 32 },
  rowWrapper: {
    backgroundColor: colors.card,
    borderRadius: 16,
    overflow: "hidden",
  },
  busyBadge: { position: "absolute", right: spacing.lg, top: 22 },
  feedback: {
    fontSize: 13,
    color: colors.secondaryLabel,
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.md,
  },
});
