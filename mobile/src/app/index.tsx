/**
 * The main screen: linked PCs, each with a native long-press context menu
 * offering "Wake up" and "Unlock session".
 */

import {
  Button,
  ContentUnavailableView,
  ContextMenu,
  HStack,
  Image,
  List,
  ProgressView,
  Spacer,
  Text,
  VStack,
} from "@expo/ui/swift-ui";
import {
  accessibilityHint,
  accessibilityLabel,
  buttonBorderShape,
  buttonStyle,
  controlSize,
  font,
  foregroundStyle,
  listStyle,
  refreshable,
} from "@expo/ui/swift-ui/modifiers";
import { Stack, useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useRef } from "react";
import { Pressable, StyleSheet, Text as RNText } from "react-native";

import { usePCActions } from "@/actions/usePCActions";
import { useT, type MessageKey } from "@/i18n";
import { usePCStore } from "@/state/store";
import type { LinkedPC, PCStatusSnapshot } from "@/state/types";
import { PAIR_COMMAND } from "@/ui/copy";
import { Screen } from "@/ui/Screen";
import { statusColor, statusSymbol } from "@/ui/status";
import { colors, secondaryText, tertiaryText } from "@/ui/theme";

/** A row's own status poll, handed up so pull-to-refresh can await all of them. */
type Refresher = () => Promise<void>;

export default function PCListScreen() {
  const pcs = usePCStore((state) => state.pcs);
  const statuses = usePCStore((state) => state.statuses);
  const router = useRouter();
  const t = useT();

  /**
   * Each row lends the list its `refresh`.
   *
   * SwiftUI's `refreshable` keeps the spinner up until the promise it is given
   * resolves, so the list has to actually await the polls rather than poke the
   * rows and hope. Rows own their own actions, hence the registry.
   */
  const refreshers = useRef(new Map<string, Refresher>());
  const register = useCallback((id: string, refresh: Refresher) => {
    refreshers.current.set(id, refresh);
    return () => {
      refreshers.current.delete(id);
    };
  }, []);
  const refreshAll = useCallback(async () => {
    await Promise.all(Array.from(refreshers.current.values(), (refresh) => refresh()));
  }, []);

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

      <Screen>
        {pcs.length === 0 ? (
          <EmptyState />
        ) : (
          <List modifiers={[listStyle("insetGrouped"), refreshable(refreshAll)]}>
            {pcs.map((pc) => (
              <PCRow key={pc.id} pc={pc} status={statuses[pc.id]} register={register} />
            ))}
          </List>
        )}
      </Screen>
    </>
  );
}

function EmptyState() {
  const router = useRouter();
  const t = useT();
  return (
    <VStack spacing={20}>
      <ContentUnavailableView
        title={t("list.empty.title")}
        systemImage="desktopcomputer"
        description={t("list.empty.body", { cmd: PAIR_COMMAND })}
      />
      <Button
        label={t("nav.addPC")}
        systemImage="plus"
        onPress={() => router.push("/discover")}
        modifiers={[
          buttonStyle("glassProminent"),
          buttonBorderShape("capsule"),
          controlSize("large"),
        ]}
      />
    </VStack>
  );
}

/**
 * One row.
 *
 * The row is a SwiftUI `ContextMenu` around a plain-styled `Button`, so a tap
 * opens the detail screen and a long press produces the real iOS menu with its
 * blur and preview rather than a modal imitation of one. It used to be a
 * SwiftUI host with a transparent React Native `Pressable` laid over it to
 * catch the tap; inside a native `List` there is nothing for such an overlay to
 * sit on, and the button is what SwiftUI wanted in the first place.
 */
function PCRow({
  pc,
  status,
  register,
}: {
  pc: LinkedPC;
  status: PCStatusSnapshot | undefined;
  register: (id: string, refresh: Refresher) => () => void;
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

  // `refresh` is stable for the life of the row, so this registers once.
  useEffect(() => register(pc.id, refresh), [register, pc.id, refresh]);

  const openDetails = useCallback(
    () => router.push({ pathname: "/pc/[id]", params: { id: pc.id } }),
    [router, pc.id],
  );

  const canUnlock = pc.capabilities.includes("unlock");
  const canWake = pc.wake.macs.length > 0;
  const subtitle = describe(pc, status, busy, t);

  return (
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
        <Button
          onPress={openDetails}
          modifiers={[
            buttonStyle("plain"),
            accessibilityLabel(`${pc.name}. ${subtitle}`),
            accessibilityHint(t("list.a11y.rowHint")),
          ]}
        >
          <HStack spacing={14}>
            <Image systemName={statusSymbol(status)} size={26} color={statusColor(status)} />
            <VStack alignment="leading" spacing={2}>
              <Text modifiers={[font({ size: 17, weight: "semibold" })]}>{pc.name}</Text>
              <Text modifiers={[font({ size: 13 }), secondaryText]}>
                {subtitle}
              </Text>
              {feedback ? (
                <Text
                  modifiers={[font({ size: 13 }), foregroundStyle(feedbackColor(feedback.tone))]}
                >
                  {feedback.message}
                </Text>
              ) : null}
            </VStack>
            <Spacer />
            {busy ? (
              <ProgressView />
            ) : (
              <Image
                systemName="chevron.right"
                size={13}
                modifiers={[tertiaryText]}
              />
            )}
          </HStack>
        </Button>
      </ContextMenu.Trigger>
    </ContextMenu>
  );
}

function feedbackColor(tone: "success" | "error" | "info") {
  if (tone === "error") return "red";
  if (tone === "success") return "green";
  return "secondary";
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
  addButton: { fontSize: 28, color: colors.tint, lineHeight: 32 },
  headerGlyph: { fontSize: 20, color: colors.tint, lineHeight: 32 },
});
