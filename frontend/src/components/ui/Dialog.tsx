import type { ReactNode } from "react";

interface DialogProps {
  open: boolean;
  onClose: () => void;
  label: string;
  children: ReactNode;
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
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div aria-hidden onClick={onClose} className="fixed inset-0 bg-deck-950/70" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={label}
        className={`relative z-10 w-full max-w-sm rounded-xl border border-deck-700 bg-deck-900 p-5 shadow-lg ${className ?? ""}`}
      >
        {children}
      </div>
    </div>
  );
}
