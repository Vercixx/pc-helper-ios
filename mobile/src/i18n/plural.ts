/**
 * Plural selection.
 *
 * English needs two forms and Russian needs three, so a message whose wording
 * depends on a count is stored as an object rather than a string and the form
 * is chosen per language. The rules are CLDR's, restricted to the integer
 * counts this app actually has (packets sent) — no fractions, no ordinals.
 */

export type Plural = {
  /** 1 packet / 1 пакет */
  one: string;
  /** 2–4 пакета. Absent for languages that do not distinguish it. */
  few?: string;
  /** The catch-all: "other" in English, 5+ / 11–14 in Russian. */
  many: string;
};

export type Message = string | Plural;

export type PluralForm = keyof Plural;

export function isPlural(message: Message): message is Plural {
  return typeof message !== "string";
}

/**
 * Which form `count` takes in `locale`.
 *
 * Falls back to `many` whenever the chosen form is missing, so a catalogue that
 * omits `few` still resolves rather than rendering undefined.
 */
export function pluralForm(locale: string, count: number): PluralForm {
  const n = Math.abs(Math.trunc(count));

  if (locale === "ru") {
    const mod10 = n % 10;
    const mod100 = n % 100;
    if (mod10 === 1 && mod100 !== 11) return "one";
    if (mod10 >= 2 && mod10 <= 4 && !(mod100 >= 12 && mod100 <= 14)) return "few";
    return "many";
  }

  return n === 1 ? "one" : "many";
}

export function selectPlural(message: Plural, locale: string, count: number): string {
  const form = pluralForm(locale, count);
  return message[form] ?? message.many;
}
