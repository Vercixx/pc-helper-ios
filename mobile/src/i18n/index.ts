/**
 * Translation.
 *
 * Two entry points, because half the strings in this app are produced outside
 * React: `useT()` for components, which re-renders when the language changes,
 * and `t()` for everything else (actions, `ApiError.friendly`).
 *
 * What this does *not* cover: App Intents, the widget, and the iOS permission
 * prompts. Those are resolved by the system from the bundle's `.lproj`
 * resources, often before the app is even running, so they follow the system
 * language and ignore the override here. See docs/I18N.md.
 */

import { getLocales } from "expo-localization";
import { useCallback } from "react";

import { en, type Catalog, type MessageKey } from "./en";
import { isPlural, selectPlural } from "./plural";
import { ru } from "./ru";
import { useLanguageStore, type LanguageSetting } from "./store";

export type { LanguageSetting } from "./store";
export type { MessageKey } from "./en";
export { useLanguageStore } from "./store";

/** Languages with a catalogue. `en` is the fallback for anything else. */
export type Locale = "en" | "ru";

export const LOCALES: readonly Locale[] = ["en", "ru"];

const catalogs: Record<Locale, Catalog> = { en, ru };

/** Substitutions for `{placeholder}` spans. */
export type Params = Record<string, string | number>;

/**
 * The phone's preference, first supported language wins.
 *
 * Read lazily and cached: `getLocales()` is a synchronous bridge call, and the
 * system language cannot change without restarting the app anyway.
 */
let cachedSystemLocale: Locale | undefined;

export function systemLocale(): Locale {
  if (cachedSystemLocale) return cachedSystemLocale;
  cachedSystemLocale = "en";
  try {
    for (const locale of getLocales()) {
      const code = locale.languageCode;
      if (code && (LOCALES as readonly string[]).includes(code)) {
        cachedSystemLocale = code as Locale;
        break;
      }
    }
  } catch {
    // No native module (Expo Go edge cases, unit tests). English it is.
  }
  return cachedSystemLocale;
}

export function resolveLocale(setting: LanguageSetting): Locale {
  return setting === "system" ? systemLocale() : setting;
}

/** The locale currently in force, for `t()` and for date formatting. */
export function currentLocale(): Locale {
  return resolveLocale(useLanguageStore.getState().language);
}

function interpolate(text: string, params: Params | undefined): string {
  if (!params) return text;
  return text.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole,
  );
}

export function translate(locale: Locale, key: MessageKey, params?: Params): string {
  // `en` is consulted when a catalogue somehow lacks the key at runtime --
  // the types prevent it, but a stale persisted language must not blank the UI.
  const message = catalogs[locale][key] ?? en[key];
  const text = isPlural(message)
    ? selectPlural(message, locale, Number(params?.count ?? 0))
    : message;
  return interpolate(text, params);
}

/** Translate outside React. Reads the language at call time. */
export function t(key: MessageKey, params?: Params): string {
  return translate(currentLocale(), key, params);
}

/** Translate inside React, re-rendering when the language changes. */
export function useT(): (key: MessageKey, params?: Params) => string {
  const locale = useLocale();
  return useCallback(
    (key: MessageKey, params?: Params) => translate(locale, key, params),
    [locale],
  );
}

export function useLocale(): Locale {
  return resolveLocale(useLanguageStore((state) => state.language));
}

/**
 * Split a translated string around a placeholder so the middle can be rendered
 * as its own element -- a command name in a monospace `<Text>`, say.
 *
 * The alternative, cutting the sentence into two catalogue entries, would fix
 * the word order in English and make several of these untranslatable.
 */
export function splitAround(text: string, token: string): [string, string] {
  const marker = `{${token}}`;
  const at = text.indexOf(marker);
  if (at === -1) return [text, ""];
  return [text.slice(0, at), text.slice(at + marker.length)];
}
