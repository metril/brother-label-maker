import { create } from "zustand";
import type { LabelDefinition, Sequence } from "../api/types";

/** The Designer page's "current, unsaved design" as far as the chain
 * preview drawer needs it: exactly the fields TrayPanel.tsx feeds into
 * `bodyLabels`/`bodySerialization` when the tray is empty. Mirrored here
 * by pages/Designer.tsx (an effect, cleared on unmount) because that
 * design lives in Designer's local render state -- no store carries it --
 * and the drawer mounts in AppShell, far outside Designer's subtree. */
export interface CurrentDesignMirror {
  definition: LabelDefinition;
  serialization: Sequence | null;
  canSubmit: boolean;
}

interface ChainPreviewState {
  open: boolean;
  currentDesign: CurrentDesignMirror | null;
  openDrawer: () => void;
  closeDrawer: () => void;
  toggle: () => void;
  setCurrentDesign: (design: CurrentDesignMirror | null) => void;
}

/** Rework of Track C2's "Preview chain" surface: open/close for
 * components/ChainPreviewDrawer.tsx, the ONLY thing shared between every
 * components/TrayPanel.tsx instance (JobTray.tsx's sidebar/sheet on the
 * Design route, GlobalTrayDrawer.tsx's own slide-over everywhere else) and
 * the drawer itself -- which now mounts exactly once, at AppShell level, on
 * EVERY route (see AppShell.tsx). A plain `useState` inside the drawer
 * couldn't do this job: TrayPanel's own "Preview chain" button lives in a
 * different React subtree than the drawer that must react to it (see
 * ChainPreviewDrawer.tsx's own docstring on why the drawer can't simply be
 * a child of TrayPanel the way the old centered ChainedPreviewDialog was).
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
 * estimate already does, rather than have every TrayPanel instance push a
 * second, driftable copy of the tray body through this store on every
 * render. The ONE piece of data that does travel through here is
 * `currentDesign` (see CurrentDesignMirror above): the empty-tray
 * fallback the old centered dialog got for free from TrayPanel's props,
 * which no store carries. */
export const useChainPreviewStore = create<ChainPreviewState>((set) => ({
  open: false,
  currentDesign: null,
  openDrawer: () => set({ open: true }),
  closeDrawer: () => set({ open: false }),
  toggle: () => set((state) => ({ open: !state.open })),
  setCurrentDesign: (design) => set({ currentDesign: design }),
}));
