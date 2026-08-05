/**
 * The native catalogues, which nothing else can check.
 *
 * Swift string keys are plain literals: a typo, or a key that exists in the
 * source but not in `Localizable.strings`, compiles cleanly and then renders
 * the English `defaultValue` on a Russian phone. That is invisible short of
 * setting the device language and reading every screen, so it is pinned here
 * instead.
 *
 * Three separate bundles are involved and they must not be confused:
 *   - the app target, fed from `locales/<lang>.json` by Expo's `locales` config
 *   - the widget extension, which is its own bundle, fed from
 *     `targets/widget/<lang>.lproj/`
 *   - Siri phrases, in `locales/ios/<lang>.lproj/AppShortcuts.strings`
 */

import fs from "fs";
import path from "path";

const ROOT = path.resolve(__dirname, "../../..");

const LANGUAGES = ["en", "ru"] as const;
type Language = (typeof LANGUAGES)[number];

/** `"key" = "value";`, ignoring /* … *​/ comments. */
function parseStrings(file: string): Map<string, string> {
  const text = fs.readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  const entries = new Map<string, string>();
  for (const match of text.matchAll(/"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"\s*;/g)) {
    const [, key, value] = match;
    if (key !== undefined && value !== undefined) entries.set(key, value);
  }
  return entries;
}

function appCatalogue(language: Language): Record<string, string> {
  const json = JSON.parse(fs.readFileSync(path.join(ROOT, "locales", `${language}.json`), "utf8"));
  const table = json.ios["Localizable.strings"] as Record<string, string>;
  // Keys are stored pre-quoted so Expo emits them quoted; strip that here.
  return Object.fromEntries(
    Object.entries(table).map(([key, value]) => [key.replace(/^"|"$/g, ""), value]),
  );
}

function widgetCatalogue(language: Language): Map<string, string> {
  return parseStrings(path.join(ROOT, "targets", "widget", `${language}.lproj`, "Localizable.strings"));
}

function shortcutsCatalogue(language: Language): Map<string, string> {
  return parseStrings(
    path.join(ROOT, "locales", "ios", `${language}.lproj`, "AppShortcuts.strings"),
  );
}

/** Every `String(localized: "…")` / `LocalizedStringResource("…")` key in a directory. */
function keysUsedIn(directory: string): Set<string> {
  const keys = new Set<string>();
  for (const name of fs.readdirSync(directory)) {
    if (!name.endsWith(".swift")) continue;
    const source = fs.readFileSync(path.join(directory, name), "utf8");
    for (const match of source.matchAll(/String\(\s*localized:\s*"([^"]+)"/g)) {
      if (match[1]) keys.add(match[1]);
    }
    for (const match of source.matchAll(/LocalizedStringResource\(\s*"([^"]+)"/g)) {
      if (match[1]) keys.add(match[1]);
    }
  }
  return keys;
}

describe("app target strings", () => {
  it("has the same keys in both languages", () => {
    expect(Object.keys(appCatalogue("ru")).sort()).toEqual(Object.keys(appCatalogue("en")).sort());
  });

  it("defines every key the app's Swift asks for", () => {
    const defined = new Set(Object.keys(appCatalogue("en")));
    const used = keysUsedIn(path.join(ROOT, "native"));
    expect([...used].filter((key) => !defined.has(key))).toEqual([]);
  });

  it("keeps the same format specifiers in both languages", () => {
    const en = appCatalogue("en");
    const ru = appCatalogue("ru");
    for (const [key, english] of Object.entries(en)) {
      const specifiers = (text: string) => (text.match(/%(\d+\$)?[@dfs]/g) ?? []).sort();
      expect({ key, specifiers: specifiers(ru[key]!) }).toEqual({
        key,
        specifiers: specifiers(english),
      });
    }
  });

  it("localizes the permission prompts users actually see", () => {
    for (const language of LANGUAGES) {
      const json = JSON.parse(
        fs.readFileSync(path.join(ROOT, "locales", `${language}.json`), "utf8"),
      );
      expect(json.NSCameraUsageDescription).toBeTruthy();
      expect(json.NSFaceIDUsageDescription).toBeTruthy();
      expect(json.NSLocalNetworkUsageDescription).toBeTruthy();
    }
  });
});

describe("widget extension strings", () => {
  it("has the same keys in both languages", () => {
    expect([...widgetCatalogue("ru").keys()].sort()).toEqual(
      [...widgetCatalogue("en").keys()].sort(),
    );
  });

  it("defines every key the widget's Swift asks for", () => {
    const defined = widgetCatalogue("en");
    const used = keysUsedIn(path.join(ROOT, "targets", "widget"));
    expect([...used].filter((key) => !defined.has(key))).toEqual([]);
  });

  it("does not rely on the app's catalogue", () => {
    // An .appex resolves against its own bundle, so anything the widget uses
    // has to be repeated here even when the app already defines it.
    const appKeys = new Set(Object.keys(appCatalogue("en")));
    const shared = [...keysUsedIn(path.join(ROOT, "targets", "widget"))].filter((key) =>
      appKeys.has(key),
    );
    for (const key of shared) expect(widgetCatalogue("en").has(key)).toBe(true);
  });
});

describe("Siri phrases", () => {
  it("translates every English phrase", () => {
    const en = shortcutsCatalogue("en");
    const ru = shortcutsCatalogue("ru");
    expect([...ru.keys()].sort()).toEqual([...en.keys()].sort());
  });

  it("covers exactly the phrases declared in Swift", () => {
    const source = fs.readFileSync(path.join(ROOT, "native", "WUAppIntents.swift"), "utf8");
    // Swift writes the token as \(.applicationName); the .strings file uses
    // Apple's ${applicationName}, and the two have to line up exactly.
    const declared = [...source.matchAll(/"([^"]*\\\(\.applicationName\)[^"]*)"/g)]
      .map((match) => match[1])
      .filter((phrase): phrase is string => phrase !== undefined)
      .map((phrase) => phrase.replace(/\\\(\.applicationName\)/g, "${applicationName}"));
    expect(declared.length).toBeGreaterThan(0);
    expect([...shortcutsCatalogue("en").keys()].sort()).toEqual(declared.sort());
  });

  it("keeps the app-name token in every translation", () => {
    for (const phrase of shortcutsCatalogue("ru").values()) {
      expect(phrase).toContain("${applicationName}");
    }
  });
});
