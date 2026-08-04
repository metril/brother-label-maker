import { create } from "zustand";
import { persist } from "zustand/middleware";

interface PrintPreviewState {
  open: boolean;
  /** Whether the drawer should render as a real in-flow FULL-WIDTH BOTTOM
   * BAND (AppShell.tsx mounts this panel as its own root column's LAST
   * child, AFTER the content row, `xl:` and up) instead of the default
   * fixed overlay -- see this file's own docstring for why this field
   * (unlike `open`) is persisted. */
  docked: boolean;
  /** Which of the loaded preview's segments PrintPreviewDeck's own
   * cycler row is showing/highlighting -- session-only, same category as
   * `open` (NOT part of PersistedPrintPreviewState below): which label
   * within the CURRENT queued job someone happens to be looking at has no
   * business surviving a reload. The drawer itself resets this back to 0
   * whenever the loaded preview's own identity changes (a tray edit/mode
   * switch changes the underlying bodyKey/segment count) or the drawer
   * opens fresh -- see PrintPreviewDeck.tsx's own effect. */
  selectedIndex: number;
  openDrawer: () => void;
  closeDrawer: () => void;
  toggle: () => void;
  toggleDocked: () => void;
  setSelectedIndex: (index: number) => void;
}

/** The subset of PrintPreviewState actually written to localStorage
 * (persist's own `partialize`) -- `docked` alone. See this file's own
 * docstring for why `open` (and every action function) stays out. */
type PersistedPrintPreviewState = Pick<PrintPreviewState, "docked">;

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
 * `open` is deliberately NOT persisted (unlike `docked` below, and unlike
 * stores/tray.ts's own queue) -- "is the chain preview drawer open right
 * now" has no business surviving a reload; it's pure transient UI state,
 * the same category hooks/useDialogController.ts's own local `isOpen`
 * already is for every OTHER dialog in this app. This store only promotes
 * that same idea to module scope.
 *
 * `docked` (the dockable-preview feature) is the OPPOSITE: whether a user
 * wants this drawer pinned in-flow, as a full-width band at the bottom of
 * the page, instead of floating over it, is a standing layout preference,
 * not per-open transient state -- worth surviving a reload the same way
 * stores/tray.ts's own chainMode/autoCut do. Persisted via zustand's
 * `persist` middleware (localStorage, key "lm-chain-preview-v1"), with
 * `partialize` limited to `{ docked }` alone
 * (see PersistedPrintPreviewState above) -- `open` stays purely in-memory,
 * same reasoning as above. See PrintPreviewDeck.tsx's own docstring for
 * the exact overlay-vs-docked class/semantics contract this flag drives.
 *
 * Deliberately NOT the vehicle for the TRAY's data (items/options/chain
 * mode) -- PrintPreviewDeck.tsx reads all of that directly off
 * stores/tray.ts itself, the same way GlobalTrayDrawer.tsx's own header
 * estimate already does, rather than have TrayPanel push a second,
 * driftable copy of the tray body through this store on every render. The
 * Designer page's own "current, unsaved design" (the empty-tray fallback
 * TrayPanel's own estimate/Print still need -- PrintPreviewDeck no
 * longer has one at all, see that component's own docstring) lives in its
 * OWN store, stores/currentDesign.ts -- this one is pure open/close (+ dock
 * preference + cycler position) state. */
export const usePrintPreviewStore = create<PrintPreviewState>()(
  persist(
    (set) => ({
      open: false,
      docked: false,
      selectedIndex: 0,
      openDrawer: () => set({ open: true }),
      closeDrawer: () => set({ open: false }),
      toggle: () => set((state) => ({ open: !state.open })),
      toggleDocked: () => set((state) => ({ docked: !state.docked })),
      setSelectedIndex: (selectedIndex) => set({ selectedIndex }),
    }),
    {
      name: "lm-chain-preview-v1",
      version: 1,
      partialize: (state): PersistedPrintPreviewState => ({ docked: state.docked }),
    },
  ),
);
