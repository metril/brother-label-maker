import { create } from "zustand";
import { persist } from "zustand/middleware";

interface PrintPreviewState {
  /** Whether the bottom preview deck is shown or hidden -- persisted (see
   * this file's own docstring): survives reloads, the same way
   * stores/tray.ts's own chainMode/autoCut do. Whether that deck renders as
   * a fixed overlay or an in-flow band is purely a breakpoint call
   * made by components/PrintPreviewDeck.tsx itself, not state stored here. */
  open: boolean;
  /** Which of the loaded preview's segments PrintPreviewDeck's own
   * cycler row is showing/highlighting -- session-only, unlike `open`
   * above (which now persists; NOT part of PersistedPrintPreviewState
   * below): which label within the CURRENT queued job someone happens to
   * be looking at has no business surviving a reload. The drawer itself
   * resets this back to 0 whenever the loaded preview's own identity
   * changes (a tray edit/mode switch changes the underlying
   * bodyKey/segment count) or the drawer opens fresh -- see
   * PrintPreviewDeck.tsx's own effect. */
  selectedIndex: number;
  openDrawer: () => void;
  closeDrawer: () => void;
  toggle: () => void;
  setSelectedIndex: (index: number) => void;
}

/** The subset of PrintPreviewState actually written to localStorage
 * (persist's own `partialize`) -- `open` alone. See this file's own
 * docstring for why `selectedIndex` (and every action function) stays
 * out. */
type PersistedPrintPreviewState = Pick<PrintPreviewState, "open">;

/** Rework of Track C2's "Preview" surface: open/close for
 * components/PrintPreviewDeck.tsx, the thing shared between
 * components/TrayPanel.tsx (rendered by components/GlobalTrayDrawer.tsx,
 * the one tray UI on every route) and the drawer itself -- which mounts
 * exactly once, at AppShell level, on EVERY route (see AppShell.tsx). A
 * plain `useState` inside the drawer couldn't do this job: TrayPanel's own
 * "Preview" button lives in a different React subtree than the drawer that
 * must react to it (see PrintPreviewDeck.tsx's own docstring on why the
 * drawer can't simply be a child of TrayPanel the way the old centered
 * ChainedPreviewDialog was).
 *
 * `open` IS persisted (zustand's `persist` middleware, localStorage, key
 * "lm-chain-preview-v1") -- whether the bottom preview deck is shown or
 * hidden is a standing preference worth surviving a reload, the same way
 * stores/tray.ts's own chainMode/autoCut do. `partialize` is limited to
 * `{ open }` alone (see PersistedPrintPreviewState above). Docking has been
 * removed from the app entirely: whether the deck renders as a fixed
 * overlay or an in-flow band is no longer stored state at all -- it's a
 * breakpoint-driven layout call made entirely inside
 * components/PrintPreviewDeck.tsx itself (see that component's own
 * docstring for the exact contract).
 *
 * Deliberately NOT the vehicle for the TRAY's data (items/options/chain
 * mode) -- PrintPreviewDeck.tsx reads all of that directly off
 * stores/tray.ts itself, the same way GlobalTrayDrawer.tsx's own header
 * estimate already does, rather than have TrayPanel push a second,
 * driftable copy of the tray body through this store on every render. The
 * Designer page's own "current, unsaved design" (the empty-tray fallback
 * TrayPanel's own estimate/Print still need -- PrintPreviewDeck no
 * longer has one at all, see that component's own docstring) lives in its
 * OWN store, stores/currentDesign.ts -- this one is pure open/close (+
 * cycler position) state. */
export const usePrintPreviewStore = create<PrintPreviewState>()(
  persist(
    (set) => ({
      open: false,
      selectedIndex: 0,
      openDrawer: () => set({ open: true }),
      closeDrawer: () => set({ open: false }),
      toggle: () => set((state) => ({ open: !state.open })),
      setSelectedIndex: (selectedIndex) => set({ selectedIndex }),
    }),
    {
      name: "lm-chain-preview-v1",
      version: 2,
      partialize: (state): PersistedPrintPreviewState => ({ open: state.open }),
      migrate: (persistedState, version) =>
        version < 2
          ? { open: Boolean((persistedState as { docked?: boolean }).docked) }
          : (persistedState as PersistedPrintPreviewState),
    },
  ),
);
