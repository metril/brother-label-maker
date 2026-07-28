import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";

export interface DialogController {
  isOpen: boolean;
  open: () => void;
  close: () => void;
  /** Attach to whichever control inside the dialog should receive focus the
   * instant it opens (this app's convention: a "×" close button, or a
   * non-destructive Cancel for a confirm dialog -- never the destructive
   * action itself). */
  closeButtonRef: RefObject<HTMLButtonElement>;
}

/** Shared open/close + focus-management contract for this app's page-level
 * dialogs (task 2.13: Save-as-preset, Rename, Delete-confirm, History
 * details) -- lifted out of components/JobTray.tsx's mobile sheet (task
 * 2.12), which established the pattern this app follows for every dialog:
 * remember what had focus before opening, move focus onto a designated
 * control the instant it opens, close on Escape, and restore focus to the
 * trigger on close. Deliberately no full focus TRAP (Tab wrapping back to
 * the first/last element) -- JobTray's own docstring made the same call:
 * optional per that task's review, and still optional here. */
export function useDialogController(): DialogController {
  const [isOpen, setIsOpen] = useState(false);
  const triggerRef = useRef<HTMLElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  function open() {
    triggerRef.current = document.activeElement as HTMLElement | null;
    setIsOpen(true);
  }

  function close() {
    setIsOpen(false);
    triggerRef.current?.focus?.();
    triggerRef.current = null;
  }

  useEffect(() => {
    if (!isOpen) return;
    closeButtonRef.current?.focus();
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") close();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isOpen]);

  return { isOpen, open, close, closeButtonRef };
}
