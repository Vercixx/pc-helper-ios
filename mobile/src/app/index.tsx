/**
 * The main screen: linked PCs, each with a native long-press context menu
 * offering "Wake up" and "Unlock session".
 */

import { Button, ContextMenu, HStack, Host, Image, Spacer, Text, VStack } from "@expo/ui/swift-ui";
import { font, foregroundColor, frame, padding } from "@expo/ui/swift-ui/modifiers";
import { Stack, useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
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
import { usePCStore } from "@/state/store";
import type { LinkedPC, PCStatusSnapshot } from "@/state/types";
import { colors, spacing, styles as shared } from "@/ui/theme";

export default function PCListScreen() {
  const pcs = usePCStore((state) => state.pcs);
  const statuses = usePCStore((state) => state.statuses);
  const [nonce, setNonce] = useState(0);
  const router = useRouter();

  return (
    <>
      <Stack.Screen
        options={{
          headerRight: () => (
            <Pressable
              accessibilityLabel="Add a PC"
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
          <RefreshControl refreshing={false} onRefresh={() => setNonce((n) => n + 1)} />
        }
      >
        {pcs.length === 0 ? (
          <EmptyState />
        ) : (
          pcs.map((pc) => (
            <PCRow key={`${pc.id}:${nonce}`} pc={pc} status={statuses[pc.id]} />
          ))
        )}
      </ScrollView>
    </>
  );
}

function EmptyState() {
  const router = useRouter();
  return (
    <View style={shared.centered}>
      <RNText style={local.emptyGlyph}>🖥️</RNText>
      <RNText style={shared.title}>No PCs yet</RNText>
      <RNText style={[shared.caption, local.centerText]}>
        On your Linux PC run <RNText style={shared.mono}>wol-unlockctl pair</RNText>, then
        tap ＋ to scan the code it shows.
      </RNText>
      {/* Not <Link asChild>: it clones the child with its own props, which
          clobbers an array `style` and drops the button's background. */}
      <Pressable
        style={[shared.primaryButton, local.stretch]}
        accessibilityRole="button"
        onPress={() => router.push("/discover")}
      >
        <RNText style={shared.primaryButtonLabel}>Add a PC</RNText>
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
function PCRow({ pc, status }: { pc: LinkedPC; status: PCStatusSnapshot | undefined }) {
  const router = useRouter();
  const { busy, feedback, refresh, wake, unlock } = usePCActions(pc);

  // Refresh whenever the list comes back into view, so what is shown is never
  // left over from a previous app session.
  useFocusEffect(
    useCallback(() => {
      void refresh();
    }, [refresh]),
  );

  const openDetails = useCallback(
    () => router.push({ pathname: "/pc/[id]", params: { id: pc.id } }),
    [router, pc.id],
  );

  const canUnlock = pc.capabilities.includes("unlock");
  const canWake = pc.wake.macs.length > 0;
  const subtitle = describe(pc, status, busy);

  return (
    <View style={local.rowWrapper}>
      <Host matchContents>
        <ContextMenu>
          <ContextMenu.Items>
            {canWake ? (
              <Button label="Wake up" systemImage="power" onPress={() => void wake()} />
            ) : null}
            {canUnlock ? (
              <Button
                label="Unlock session"
                systemImage="lock.open"
                onPress={() => void unlock()}
              />
            ) : null}
            <Button
              label="Refresh"
              systemImage="arrow.clockwise"
              onPress={() => void refresh()}
            />
            <Button label="Details" systemImage="info.circle" onPress={openDetails} />
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
        accessibilityHint="Opens details. Long press for wake and unlock."
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
): string {
  if (busy === "wake") return "Waking…";
  if (busy === "unlock") return "Unlocking…";
  if (busy === "status") return "Checking…";
  if (!status) return pc.hostname;
  if (!status.reachable) return status.error ?? "Asleep or unreachable";
  if (status.locked === null) return "Online — nobody logged in";
  return status.locked ? "Locked — long press to unlock" : "Unlocked";
}

const local = StyleSheet.create({
  list: { padding: spacing.lg, gap: spacing.md },
  emptyContainer: { flexGrow: 1 },
  emptyGlyph: { fontSize: 56 },
  centerText: { textAlign: "center" },
  stretch: { alignSelf: "stretch", marginTop: spacing.lg },
  addButton: { fontSize: 28, color: colors.tint, lineHeight: 32 },
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
