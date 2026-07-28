import type { RefObject } from "react";
import { Dialog } from "./ui/Dialog";
import { errorText } from "./ui/styles";

interface ConfirmDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  closeButtonRef: RefObject<HTMLButtonElement>;
  label: string;
  message: string;
  confirmLabel?: string;
  isPending?: boolean;
  error?: string | null;
}

/** A destructive-action confirm dialog, shared by Presets' and History's
 * own "Delete" actions -- reuses ui/Dialog.tsx + useDialogController's
 * shared open/close/focus contract (lifted from JobTray.tsx's mobile
 * sheet) so every "are you sure?" in this app behaves identically: focus
 * moves onto Cancel the instant it opens (never straight onto the
 * destructive action itself), Escape/backdrop-click/Cancel all close it
 * without confirming, and the whole thing is reachable and operable by
 * keyboard alone. */
export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  closeButtonRef,
  label,
  message,
  confirmLabel = "Delete",
  isPending = false,
  error = null,
}: ConfirmDialogProps) {
  return (
    <Dialog open={open} onClose={onClose} label={label}>
      <p className="text-[14px] text-deck-200">{message}</p>
      {error && (
        <p role="alert" className={errorText}>
          {error}
        </p>
      )}
      <div className="mt-4 flex justify-end gap-2">
        <button
          type="button"
          ref={closeButtonRef}
          onClick={onClose}
          className="rounded-md border border-deck-600 bg-deck-800 px-4 py-2 text-[13px] font-medium text-deck-200 transition-colors hover:border-deck-400"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={isPending}
          className="rounded-md border border-rust-500 bg-rust-500 px-4 py-2 text-[13px] font-semibold text-deck-950 transition-colors hover:bg-rust-500/80 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isPending ? "Deleting…" : confirmLabel}
        </button>
      </div>
    </Dialog>
  );
}
