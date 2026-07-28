import { create } from "zustand";
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

/** Task 2.12: the print QUEUE (several accumulated label snapshots) plus
 * the print OPTIONS that apply to the whole tray (chain mode/auto-cut) --
 * kept separate from stores/designer.ts (the single CURRENT design being
 * edited) rather than folded into it, since a tray item is a frozen copy
 * that must survive the user going on to edit -- or entirely switch away
 * from -- the type/params that produced it. See stores/designer.ts's own
 * docstring for the complementary "one live design" half of this split. */
export const useTrayStore = create<TrayState>((set) => ({
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
}));
