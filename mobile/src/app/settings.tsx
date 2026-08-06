/**
 * Settings. One setting so far: which language the app's own text uses.
 *
 * The override exists because a phone set to one language is not proof of which
 * language its owner wants to read — and because iOS gives no per-app language
 * control to an app that ships outside the App Store.
 */

import { Form, Picker, Section, Text } from "@expo/ui/swift-ui";
import { labelsHidden, pickerStyle, tag } from "@expo/ui/swift-ui/modifiers";
import { Stack } from "expo-router";

import { systemLocale, useT, useLanguageStore, type LanguageSetting } from "@/i18n";
import { Screen } from "@/ui/Screen";

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
      <Screen>
        <Form>
          <Section title={t("settings.language")} footer={<Text>{t("settings.language.note")}</Text>}>
            {/* `inline` inside a Form section is the checkmark list this screen
                used to draw by hand. The label is kept for VoiceOver and then
                hidden, because the section header already says the same thing. */}
            <Picker
              label={t("settings.language")}
              selection={language}
              onSelectionChange={(value) => setLanguage(value as LanguageSetting)}
              modifiers={[pickerStyle("inline"), labelsHidden()]}
            >
              {CHOICES.map((choice) => (
                <Text key={choice.value} modifiers={[tag(choice.value)]}>
                  {choice.value === "system"
                    ? `${t("settings.language.system")} · ${systemLocale().toUpperCase()}`
                    : choice.label}
                </Text>
              ))}
            </Picker>
          </Section>
        </Form>
      </Screen>
    </>
  );
}
