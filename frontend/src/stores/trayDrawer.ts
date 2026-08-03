import { create } from "zustand";
import { persist } from "zustand/middleware";

interface TrayDrawerState {
  open: boolean;
  /** Whether the drawer should render as a real in-flow right-hand column
   * (AppShell.tsx's own dock rail, `xl:` and up) instead of the default
   * fixed overlay -- see this file's own docstring for why this field
   * (unlike `open`) is persisted. */
  docked: boolean;
  openDrawer: () => void;
  closeDrawer: () => void;
  toggle: () => void;
  toggleDocked: () => void;
}

/** The subset of TrayDrawerState actually written to localStorage
 * (persist's own `partialize`) -- `docked` alone. See this file's own
 * docstring for why `open` (and every action function) stays out. */
type PersistedTrayDrawerState = Pick<TrayDrawerState, "docked">;

/** Dockable-tray feature: the presentation state for
 * components/GlobalTrayDrawer.tsx's panel (open/close + dock preference),
 * split out from stores/tray.ts on purpose -- that store owns the tray's
 * actual DATA (the queued items, chain mode, auto-cut), which has nothing
 * to do with whether the panel showing them is currently open or pinned in
 * flow. Mirrors stores/chainPreview.ts's own split for exactly the same
 * reason: components/GlobalTrayDrawer.tsx's trigger button (header, every
 * route) and its panel (also mounted once, in AppShell.tsx) are separate
 * exported pieces of that file now (GlobalTrayButton/GlobalTrayPanel) that
 * don't share a parent -- a plain `useState` inside either one couldn't
 * drive the other, so this promotes that state to module scope instead.
 *
 * `open` is deliberately NOT persisted -- "is the tray drawer open right
 * now" has no business surviving a reload, same as stores/chainPreview.ts's
 * own `open`.
 *
 * `docked` (the dockable-tray feature) IS persisted (zustand's `persist`
 * middleware, localStorage, key "lm-tray-drawer-v1"), with `partialize`
 * limited to `{ docked }` alone (see PersistedTrayDrawerState above) --
 * whether a user wants the tray pinned beside the page instead of floating
 * over it is a standing layout preference, not per-open transient state.
 * See components/GlobalTrayDrawer.tsx's own docstring for the exact
 * overlay-vs-docked class/semantics contract this flag drives, and
 * AppShell.tsx's own dock-rail docstring for how this combines with
 * stores/chainPreview.ts's own `docked` when BOTH panels are pinned at
 * once. */
export const useTrayDrawerStore = create<TrayDrawerState>()(
  persist(
    (set) => ({
      open: false,
      docked: false,
      openDrawer: () => set({ open: true }),
      closeDrawer: () => set({ open: false }),
      toggle: () => set((state) => ({ open: !state.open })),
      toggleDocked: () => set((state) => ({ docked: !state.docked })),
    }),
    {
      name: "lm-tray-drawer-v1",
      version: 1,
      partialize: (state): PersistedTrayDrawerState => ({ docked: state.docked }),
    },
  ),
);
