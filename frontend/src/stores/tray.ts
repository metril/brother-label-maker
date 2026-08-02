import { create } from "zustand";
import { persist } from "zustand/middleware";
import { nextTrayItemId } from "../lib/tray";
import type { ChainMode, LabelDefinition } from "../api/types";

/** One queued label in the job tray -- a DEEP-COPIED snapshot (task 2.12's
 * "Add to tray" takes a copy, not a live reference) of a definition at the
 * moment it was added, plus enough of its own last preview to render a
 * thumbnail/length without re-fetching. `label` is the short "type + first
 * text line" caption (lib/tray.ts's describeCurrentDesign). */
export interface TrayItem {
  id: string;
  definition: LabelDefinition;
  png: string | null;
  lengthMm: number | null;
  label: string;
}

interface TrayState {
  items: TrayItem[];
  chainMode: ChainMode;
  autoCut: boolean;

  /** Appends a new item built from a snapshot (own id assigned here). */
  addItem: (item: Omit<TrayItem, "id">) => void;
  removeItem: (id: string) => void;
  duplicateItem: (id: string) => void;
  moveUp: (id: string) => void;
  moveDown: (id: string) => void;
  clear: () => void;
  setChainMode: (mode: ChainMode) => void;
  setAutoCut: (autoCut: boolean) => void;
}

/** The subset of TrayState actually written to localStorage (persist's own
 * `partialize`) -- every field except the action functions themselves
 * (which can't survive JSON.stringify anyway, and are always the SAME
 * functions from this module regardless). `items` is remapped to null out
 * each item's own `png`: a captured preview can be several KB of base64 per
 * item, and is always cheaply refetchable from the item's frozen
 * `definition` (see hooks/useTrayPreviews.ts) -- there's no reason to grow
 * localStorage with image data that's purely decorative. */
type PersistedTrayState = Pick<TrayState, "items" | "chainMode" | "autoCut">;

/** Task 2.12: the print QUEUE (several accumulated label snapshots) plus
 * the print OPTIONS that apply to the whole tray (chain mode/auto-cut) --
 * kept separate from stores/designer.ts (the single CURRENT design being
 * edited) rather than folded into it, since a tray item is a frozen copy
 * that must survive the user going on to edit -- or entirely switch away
 * from -- the type/params that produced it. See stores/designer.ts's own
 * docstring for the complementary "one live design" half of this split.
 *
 * Persisted (localStorage, key "lm-tray-v1") so a tray survives a page
 * reload/tab close -- the whole point of a queue is accumulating several
 * designs before printing them together, which a browser refresh used to
 * silently wipe. `png` is deliberately nulled on write (see
 * PersistedTrayState's own doc) and re-hydrated on demand by
 * hooks/useTrayPreviews.ts, never written back here. `version`/`migrate`
 * are a passthrough for now (this is the first persisted shape) -- a
 * future change to TrayItem's own fields bumps `version` and gives
 * `migrate` an actual transform to write. */
export const useTrayStore = create<TrayState>()(
  persist(
    (set) => ({
      items: [],
      chainMode: "cut_each",
      autoCut: true,

      addItem: (item) => set((state) => ({ items: [...state.items, { ...item, id: nextTrayItemId() }] })),

      removeItem: (id) => set((state) => ({ items: state.items.filter((i) => i.id !== id) })),

      duplicateItem: (id) =>
        set((state) => {
          const index = state.items.findIndex((i) => i.id === id);
          if (index === -1) return state;
          const copy: TrayItem = { ...state.items[index]!, id: nextTrayItemId() };
          const items = [...state.items];
          items.splice(index + 1, 0, copy);
          return { items };
        }),

      moveUp: (id) =>
        set((state) => {
          const index = state.items.findIndex((i) => i.id === id);
          if (index <= 0) return state;
          const items = [...state.items];
          [items[index - 1], items[index]] = [items[index]!, items[index - 1]!];
          return { items };
        }),

      moveDown: (id) =>
        set((state) => {
          const index = state.items.findIndex((i) => i.id === id);
          if (index === -1 || index >= state.items.length - 1) return state;
          const items = [...state.items];
          [items[index], items[index + 1]] = [items[index + 1]!, items[index]!];
          return { items };
        }),

      clear: () => set({ items: [] }),

      setChainMode: (chainMode) => set({ chainMode }),
      setAutoCut: (autoCut) => set({ autoCut }),
    }),
    {
      name: "lm-tray-v1",
      version: 1,
      partialize: (state): PersistedTrayState => ({
        items: state.items.map((item) => ({ ...item, png: null })),
        chainMode: state.chainMode,
        autoCut: state.autoCut,
      }),
      migrate: (persistedState) => persistedState as TrayState,
    },
  ),
);
