import { usePrintEstimate } from "../hooks/usePrintEstimate";
import { useDialogController } from "../hooks/useDialogController";
import { useTrayStore } from "../stores/tray";
import { TrayPanel } from "./TrayPanel";
import { eyebrow, iconButtonClass } from "./ui/styles";
import type { LabelDefinition, PrintOptions } from "../api/types";

/** Makes the print tray reachable from every route OTHER than the Designer
 * page (see AppShell.tsx, which mounts this only when `pathname !== "/"` --
 * the Designer page already has its own always-visible tray,
 * components/JobTray.tsx) via a header button ("Tray · N[, X.X mm]") that
 * opens a right-side slide-over rendering the SAME tray CONTENT
 * (components/TrayPanel.tsx) JobTray.tsx renders, with `current={null}`:
 * there is no "current, unsaved design" to fall back to or add from away
 * from the page that owns one -- see TrayPanel's own CurrentDesign doc.
 * Hidden entirely while the tray is empty -- nothing to act on, and no
 * reason to occupy header space with a control that can't do anything yet.
 *
 * Open/close/focus conventions reuse hooks/useDialogController.ts -- the
 * shared abstraction of components/JobTray.tsx's own mobile-sheet pattern
 * (task 2.12) every other dialog in this app already builds on: focus
 * moves onto the close button the instant it opens, Escape closes, and
 * focus returns to the trigger button on close. The panel itself stays
 * mounted (visibility/transform-toggled, not conditionally unmounted) the
 * same way JobTray's own mobile sheet does -- an in-flight print job's
 * hooks/usePrintJob.ts state (WS-tracked progress, in particular) would
 * otherwise be destroyed the instant the drawer closes. */
export function GlobalTrayDrawer() {
  const items = useTrayStore((s) => s.items);
  const chainMode = useTrayStore((s) => s.chainMode);
  const autoCut = useTrayStore((s) => s.autoCut);
  const dialog = useDialogController();

  // Mirrors TrayPanel's own (simpler, current-less) body derivation purely
  // to summarize the header button's own label -- see JobTray.tsx's own
  // comment on why this is duplicated rather than lifted: identical
  // usePrintEstimate inputs share the same react-query cache entry, so this
  // costs no extra request beyond whatever TrayPanel itself already fetched
  // while the drawer is open.
  const bodyLabels: LabelDefinition[] = items.map((i) => i.definition);
  const options: PrintOptions = { chain_mode: chainMode, margin_mm: 2.0, auto_cut: autoCut };
  const { estimate } = usePrintEstimate(bodyLabels, options, (labels) => labels.length > 0, null);

  // Rules of Hooks: every hook above must run on every render, so this
  // early return -- the brief's own "hide entirely when empty" -- comes
  // last, after them, not before.
  if (items.length === 0) return null;

  const label = `Tray · ${items.length}${estimate ? `, ${estimate.total_mm.toFixed(1)} mm` : ""}`;

  return (
    <>
      <button
        type="button"
        onClick={dialog.open}
        aria-haspopup="dialog"
        className="rounded-md border border-deck-600 bg-deck-800 px-3 py-1.5 font-mono text-[12px] text-deck-200 transition-colors hover:border-deck-400"
      >
        {label}
      </button>

      {dialog.isOpen && <div aria-hidden onClick={dialog.close} className="fixed inset-0 z-40 bg-deck-950/70" />}

      {/* Always mounted (visibility/translate-toggled below), not
          conditionally unmounted -- see this component's own doc for why:
          closing mid-print must not tear down the print job's own tracked
          state. */}
      <div
        data-testid="global-tray-drawer-panel"
        role={dialog.isOpen ? "dialog" : undefined}
        aria-modal={dialog.isOpen ? true : undefined}
        aria-label={dialog.isOpen ? "Print tray" : undefined}
        className={`fixed inset-y-0 right-0 z-50 flex w-full max-w-sm flex-col gap-4 overflow-y-auto border-l border-deck-800 bg-deck-900 p-5 shadow-lg transition-transform duration-150 motion-reduce:transition-none ${
          dialog.isOpen ? "visible translate-x-0" : "invisible translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between">
          <span className={eyebrow}>Tray</span>
          <button
            type="button"
            ref={dialog.closeButtonRef}
            onClick={dialog.close}
            aria-label="Close print tray"
            className={iconButtonClass}
          >
            ×
          </button>
        </div>
        <TrayPanel current={null} />
      </div>
    </>
  );
}
