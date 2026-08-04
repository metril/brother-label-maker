import { create } from "zustand";
import { persist } from "zustand/middleware";

interface TrayDrawerState {
  open: boolean;
  openDrawer: () => void;
  closeDrawer: () => void;
  toggle: () => void;
}

/** The subset of TrayDrawerState actually written to localStorage
 * (persist's own `partialize`) -- `open` alone. See this file's own
 * docstring for why nothing else (and every action function) stays out. */
type PersistedTrayDrawerState = Pick<TrayDrawerState, "open">;

/** The presentation state for
 * components/GlobalTrayDrawer.tsx's panel (open/close), split out from
 * stores/tray.ts on purpose -- that store owns the tray's actual DATA (the
 * queued items, chain mode, auto-cut), which has nothing to do with whether
 * the panel showing them is currently open. Mirrors stores/printPreview.ts's
 * own split for exactly the same reason: components/GlobalTrayDrawer.tsx's
 * trigger button (header, every route) and its panel (also mounted once, in
 * AppShell.tsx) are separate exported pieces of that file now
 * (GlobalTrayButton/GlobalTrayPanel) that don't share a parent -- a plain
 * `useState` inside either one couldn't drive the other, so this promotes
 * that state to module scope instead.
 *
 * `open` IS persisted (zustand's `persist` middleware, localStorage, key
 * "lm-tray-drawer-v1"), with `partialize` limited to `{ open }` alone (see
 * PersistedTrayDrawerState above) -- at desktop widths the tray renders as a
 * real in-flow column (not a transient overlay), so "is it shown" is a
 * standing workspace layout preference that should survive a reload, not
 * per-session state. Whether that column reads as an overlay or an in-flow
 * panel is breakpoint-driven presentation, decided in
 * components/GlobalTrayDrawer.tsx itself -- this store just tracks
 * shown/hidden and has no opinion on modality.
 *
 * `version: 2` migrates users who still have a pre-refactor `{ docked }`
 * snapshot (v1): a previously-docked tray is treated as previously-open,
 * since docking was the in-flow-and-visible state this store now models
 * directly. */
export const useTrayDrawerStore = create<TrayDrawerState>()(
  persist(
    (set) => ({
      open: false,
      openDrawer: () => set({ open: true }),
      closeDrawer: () => set({ open: false }),
      toggle: () => set((state) => ({ open: !state.open })),
    }),
    {
      name: "lm-tray-drawer-v1",
      version: 2,
      partialize: (state): PersistedTrayDrawerState => ({ open: state.open }),
      migrate: (persistedState, version) =>
        version < 2
          ? { open: Boolean((persistedState as { docked?: boolean }).docked) }
          : (persistedState as PersistedTrayDrawerState),
    },
  ),
);
