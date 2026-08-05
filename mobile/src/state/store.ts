/**
 * Persisted app state.
 *
 * Only non-secret material is stored here. Private keys live in the keychain
 * (see `src/crypto/keys.ts`); this store holds the public half of the
 * relationship plus UI bookkeeping.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import { deleteDeviceKey } from "@/crypto/keys";

import type { LinkedPC, PCStatusSnapshot } from "./types";

type PCStore = {
  pcs: LinkedPC[];
  /** Transient: reachability results for this app session only. */
  statuses: Record<string, PCStatusSnapshot>;
  hydrated: boolean;

  addOrReplacePC: (pc: LinkedPC) => void;
  updatePC: (id: string, patch: Partial<LinkedPC>) => void;
  removePC: (id: string) => Promise<void>;
  renamePC: (id: string, name: string) => void;
  setStatus: (id: string, status: PCStatusSnapshot) => void;
  markHydrated: () => void;
};

export const usePCStore = create<PCStore>()(
  persist(
    (set, get) => ({
      pcs: [],
      statuses: {},
      hydrated: false,

      addOrReplacePC: (pc) =>
        set((state) => {
          // Keyed by server fingerprint: re-pairing the same PC updates the
          // existing row rather than producing a confusing duplicate.
          const index = state.pcs.findIndex((item) => item.id === pc.id);
          if (index === -1) return { pcs: [...state.pcs, pc] };
          const next = [...state.pcs];
          next[index] = pc;
          return { pcs: next };
        }),

      updatePC: (id, patch) =>
        set((state) => ({
          pcs: state.pcs.map((pc) => (pc.id === id ? { ...pc, ...patch } : pc)),
        })),

      renamePC: (id, name) =>
        set((state) => ({
          pcs: state.pcs.map((pc) =>
            pc.id === id ? { ...pc, name: name.trim() || pc.name } : pc,
          ),
        })),

      removePC: async (id) => {
        const pc = get().pcs.find((item) => item.id === id);
        // Drop the keychain item too, or the private key outlives the pairing.
        if (pc) await deleteDeviceKey(pc.keyAlias);
        set((state) => {
          const statuses = { ...state.statuses };
          delete statuses[id];
          return { pcs: state.pcs.filter((item) => item.id !== id), statuses };
        });
      },

      setStatus: (id, status) =>
        set((state) => ({ statuses: { ...state.statuses, [id]: status } })),

      markHydrated: () => set({ hydrated: true }),
    }),
    {
      name: "wolunlock.pcs.v1",
      version: 1,
      storage: createJSONStorage(() => AsyncStorage),
      // Reachability is meaningless after a restart, so it is not persisted.
      partialize: (state) => ({ pcs: state.pcs }),
      onRehydrateStorage: () => (state) => state?.markHydrated(),
    },
  ),
);

export const selectPC = (id: string | undefined) => (state: PCStore) =>
  id ? state.pcs.find((pc) => pc.id === id) : undefined;
