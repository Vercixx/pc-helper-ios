/**
 * The language override, persisted on its own.
 *
 * Deliberately not part of `src/state/store.ts`: that store is about paired
 * PCs, and `t()` has to be callable from modules the PC store itself imports
 * (`crypto/keys`, `api/types`). Keeping the setting here means the dependency
 * only ever points one way and there is no import cycle to reason about.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

/** "system" defers to the phone; the rest pin a language regardless. */
export type LanguageSetting = "system" | "en" | "ru";

type LanguageStore = {
  language: LanguageSetting;
  setLanguage: (language: LanguageSetting) => void;
};

export const useLanguageStore = create<LanguageStore>()(
  persist(
    (set) => ({
      language: "system",
      setLanguage: (language) => set({ language }),
    }),
    {
      name: "wolunlock.language.v1",
      version: 1,
      storage: createJSONStorage(() => AsyncStorage),
    },
  ),
);
