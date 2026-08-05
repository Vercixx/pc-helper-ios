/**
 * What the types cannot catch.
 *
 * Key coverage is already a compile error: `ru` is declared as `Catalog`, so a
 * missing or misshapen entry fails `tsc`. What no type checks is whether a
 * translation kept the *placeholders* — drop `{name}` from a Russian string and
 * the app renders a sentence with a hole in it, silently. Nor do types know
 * that Russian needs three plural forms where English needs two.
 */

import { en } from "@/i18n/en";
import { ru } from "@/i18n/ru";
import { isPlural, pluralForm, selectPlural, type Message } from "@/i18n/plural";
import { splitAround, translate } from "@/i18n";

const PLACEHOLDER = /\{(\w+)\}/g;

function placeholders(message: Message): Set<string> {
  const texts = isPlural(message)
    ? [message.one, message.few, message.many].filter((v): v is string => v !== undefined)
    : [message];
  const found = new Set<string>();
  for (const text of texts) {
    for (const match of text.matchAll(PLACEHOLDER)) {
      if (match[1]) found.add(match[1]);
    }
  }
  return found;
}

describe("catalogues", () => {
  const keys = Object.keys(en) as (keyof typeof en)[];

  it("covers every key in Russian", () => {
    expect(Object.keys(ru).sort()).toEqual(keys.slice().sort());
  });

  it.each(keys)("keeps the same placeholders in %s", (key) => {
    expect([...placeholders(ru[key])].sort()).toEqual([...placeholders(en[key])].sort());
  });

  it("gives every Russian plural all three forms", () => {
    for (const key of keys) {
      const message = ru[key];
      if (!isPlural(message)) continue;
      expect(message.few).toBeDefined();
      expect(message.one).toBeTruthy();
      expect(message.many).toBeTruthy();
    }
  });

  it("leaves no message empty", () => {
    for (const key of keys) {
      const message = ru[key];
      const text = isPlural(message) ? message.one : message;
      expect(text.length).toBeGreaterThan(0);
    }
  });
});

describe("Russian plural rules", () => {
  // CLDR: one for 1, 21, 31…; few for 2–4, 22–24…; many for 0, 5–20, 25–30…
  it.each([
    [0, "many"],
    [1, "one"],
    [2, "few"],
    [4, "few"],
    [5, "many"],
    [11, "many"],
    [12, "many"],
    [13, "many"],
    [14, "many"],
    [15, "many"],
    [21, "one"],
    [22, "few"],
    [25, "many"],
    [101, "one"],
    [111, "many"],
    [112, "many"],
  ])("puts %i in the %s form", (count, expected) => {
    expect(pluralForm("ru", count)).toBe(expected);
  });

  it("agrees with the wording actually shipped", () => {
    const sent = ru["wake.sent"];
    if (!isPlural(sent)) throw new Error("wake.sent should be a plural");
    expect(selectPlural(sent, "ru", 1)).toContain("пакет.");
    expect(selectPlural(sent, "ru", 3)).toContain("пакета.");
    expect(selectPlural(sent, "ru", 7)).toContain("пакетов.");
  });
});

describe("English plural rules", () => {
  it.each([
    [0, "many"],
    [1, "one"],
    [2, "many"],
    [21, "many"],
  ])("puts %i in the %s form", (count, expected) => {
    expect(pluralForm("en", count)).toBe(expected);
  });

  it("falls back to `many` when a form is absent", () => {
    expect(selectPlural({ one: "one", many: "many" }, "ru", 3)).toBe("many");
  });
});

describe("translate", () => {
  it("substitutes named placeholders", () => {
    expect(translate("en", "wake.awake", { name: "tower" })).toBe("tower is awake.");
    expect(translate("ru", "wake.awake", { name: "tower" })).toBe("tower проснулся.");
  });

  it("picks the plural form from `count`", () => {
    expect(translate("en", "wake.sent", { count: 1, name: "pc" })).toBe(
      "Sent 1 magic packet. Waiting for pc…",
    );
    expect(translate("en", "wake.sent", { count: 3, name: "pc" })).toBe(
      "Sent 3 magic packets. Waiting for pc…",
    );
  });

  it("leaves an unknown placeholder alone rather than printing undefined", () => {
    expect(translate("en", "wake.awake")).toBe("{name} is awake.");
  });
});

describe("splitAround", () => {
  it("splits a sentence around its token", () => {
    expect(splitAround("run {cmd} first", "cmd")).toEqual(["run ", " first"]);
  });

  it("survives a translation that dropped the token", () => {
    expect(splitAround("no token here", "cmd")).toEqual(["no token here", ""]);
  });

  it("handles a token at either end", () => {
    expect(splitAround("{cmd} then", "cmd")).toEqual(["", " then"]);
    expect(splitAround("then {cmd}", "cmd")).toEqual(["then ", ""]);
  });
});
