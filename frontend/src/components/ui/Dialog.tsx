import type { ReactNode } from "react";
import { createPortal } from "react-dom";

interface DialogProps {
  open: boolean;
  onClose: () => void;
  label: string;
  children: ReactNode;
  /** REPLACES the default `max-w-sm` (it doesn't merge with it -- two
   * max-w-* utilities on one element resolve by stylesheet order, not by
   * who passed them, so merging made overrides like `max-w-2xl` silently
   * lose). A caller that passes className owns the dialog's max-width. */
  className?: string;
}

/** A small centered modal -- role="dialog"/aria-modal, backdrop click
 * closes it (Escape is wired by hooks/useDialogController.ts, not here;
 * pair every use of this component with that hook for the open/close/
 * focus contract lifted from components/JobTray.tsx's mobile sheet, task
 * 2.12). Unlike JobTray's own panel -- which stays permanently MOUNTED
 * (visibility-toggled) because it doubles as an always-visible desktop
 * sidebar -- every dialog built from this component is a pure modal with
 * no such dual role, so a plain conditional-unmount is correct and
 * simpler here. */
export function Dialog({ open, onClose, label, children, className }: DialogProps) {
  if (!open) return null;
  // Portaled to <body>: ancestors that carry a CSS `translate` (JobTray's
  // mobile sheet / lg sidebar and GlobalTrayDrawer's slide-over both do,
  // even at translate-y-0) become the containing block for position:fixed
  // descendants, which traps the modal inside that ancestor's box instead
  // of the viewport. jsdom can't see this -- it only reproduces in a real
  // layout engine.
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div aria-hidden onClick={onClose} className="fixed inset-0 bg-scrim/70" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={label}
        className={`relative z-10 w-full rounded-xl border border-deck-700 bg-deck-900 p-5 shadow-[var(--shadow-panel)] ${className ?? "max-w-sm"}`}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}
