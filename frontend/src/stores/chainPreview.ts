import { create } from "zustand";

interface ChainPreviewState {
  open: boolean;
  openDrawer: () => void;
  closeDrawer: () => void;
  toggle: () => void;
}

/** Rework of Track C2's "Preview" surface: open/close for
 * components/ChainPreviewDrawer.tsx, the thing shared between
 * components/TrayPanel.tsx (rendered by components/GlobalTrayDrawer.tsx,
 * the one tray UI on every route) and the drawer itself -- which mounts
 * exactly once, at AppShell level, on EVERY route (see AppShell.tsx). A
 * plain `useState` inside the drawer couldn't do this job: TrayPanel's own
 * "Preview" button lives in a different React subtree than the drawer that
 * must react to it (see ChainPreviewDrawer.tsx's own docstring on why the
 * drawer can't simply be a child of TrayPanel the way the old centered
 * ChainedPreviewDialog was).
 *
 * Deliberately NOT persisted (unlike stores/tray.ts's own queue) -- "is the
 * chain preview drawer open" has no business surviving a reload; it's pure
 * transient UI state, the same category hooks/useDialogController.ts's own
 * local `isOpen` already is for every OTHER dialog in this app. This store
 * only promotes that same idea to module scope.
 *
 * Deliberately NOT the vehicle for the TRAY's data (items/options/chain
 * mode) -- ChainPreviewDrawer.tsx reads all of that directly off
 * stores/tray.ts itself, the same way GlobalTrayDrawer.tsx's own header
 * estimate already does, rather than have TrayPanel push a second,
 * driftable copy of the tray body through this store on every render. The
 * Designer page's own "current, unsaved design" (the empty-tray fallback
 * both TrayPanel and ChainPreviewDrawer need) lives in its OWN store now,
 * stores/currentDesign.ts -- this one is pure open/close state. */
export const useChainPreviewStore = create<ChainPreviewState>((set) => ({
  open: false,
  openDrawer: () => set({ open: true }),
  closeDrawer: () => set({ open: false }),
  toggle: () => set((state) => ({ open: !state.open })),
}));
