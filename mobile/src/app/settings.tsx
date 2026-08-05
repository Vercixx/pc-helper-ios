/**
 * Settings. One setting so far: which language the app's own text uses.
 *
 * The override exists because a phone set to one language is not proof of which
 * language its owner wants to read — and because iOS gives no per-app language
 * control to an app that ships outside the App Store.
 */

import { Stack } from "expo-router";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { systemLocale, useT, useLanguageStore, type LanguageSetting } from "@/i18n";
import { colors, spacing, styles as shared } from "@/ui/theme";

/** Each language names itself, as language pickers everywhere do. */
const CHOICES: { value: LanguageSetting; label: string }[] = [
  { value: "system", label: "" },
  { value: "en", label: "English" },
  { value: "ru", label: "Русский" },
];

export default function SettingsScreen() {
  const t = useT();
  const language = useLanguageStore((state) => state.language);
  const setLanguage = useLanguageStore((state) => state.setLanguage);

  return (
    <>
      <Stack.Screen options={{ title: t("nav.settings") }} />
      <ScrollView style={shared.screen} contentContainerStyle={local.content}>
        <Text style={local.sectionHeader}>{t("settings.language")}</Text>

        <View style={shared.card}>
          {CHOICES.map((choice, index) => {
            const selected = language === choice.value;
            const label =
              choice.value === "system"
                ? `${t("settings.language.system")} · ${systemLocale().toUpperCase()}`
                : choice.label;
            return (
              <Pressable
                key={choice.value}
                accessibilityRole="radio"
                accessibilityState={{ selected }}
                onPress={() => setLanguage(choice.value)}
                style={[local.row, index > 0 ? local.divided : null]}
              >
                <Text style={shared.body}>{label}</Text>
                {selected ? <Text style={local.check}>✓</Text> : null}
              </Pressable>
            );
          })}
        </View>

        <Text style={[shared.caption, local.note]}>{t("settings.language.note")}</Text>
      </ScrollView>
    </>
  );
}

const local = StyleSheet.create({
  content: { padding: spacing.lg, gap: spacing.md },
  sectionHeader: {
    fontSize: 13,
    color: colors.secondaryLabel,
    marginLeft: spacing.xs,
    letterSpacing: 0.5,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: spacing.sm,
  },
  divided: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.separator,
  },
  check: { fontSize: 17, fontWeight: "600", color: colors.tint },
  note: { marginTop: spacing.xs },
});
