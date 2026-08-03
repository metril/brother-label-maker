import { usePrintEstimate } from "../hooks/usePrintEstimate";
import { useDialogController } from "../hooks/useDialogController";
import { useCurrentDesignStore } from "../stores/currentDesign";
import { useTrayStore } from "../stores/tray";
import { TrayPanel } from "./TrayPanel";
import { eyebrow, iconButtonClass } from "./ui/styles";
import type { LabelDefinition, PrintOptions } from "../api/types";

/** Makes the print tray reachable from every route -- including the
 * Designer page ("/") -- via a header button ("Tray"/"Tray · N[, X.X mm]")
 * that opens a right-side slide-over rendering components/TrayPanel.tsx.
 * The tray's own QUEUE (stores/tray.ts) is the same everywhere; the ONE
 * thing that differs by route is `current`, the Designer page's "current,
 * unsaved design" (stores/currentDesign.ts, written only by that page's
 * own mirror effect, `null` everywhere else) -- see TrayPanel's own
 * CurrentDesign doc for what that unlocks (an empty-tray print fallback,
 * "+ Add to tray"). Hidden entirely when there's nothing to act on at all
 * (empty tray AND no current design) -- nothing to occupy header space
 * for otherwise.
 *
 * Open/close/focus conventions reuse hooks/useDialogController.ts -- the
 * shared abstraction every dialog in this app builds on: focus moves onto
 * the close button the instant it opens, Escape closes, and focus returns
 * to the trigger button on close. The panel itself stays mounted
 * (visibility/transform-toggled, not conditionally unmounted) -- an
 * in-flight print job's hooks/usePrintJob.ts state (WS-tracked progress,
 * in particular) would otherwise be destroyed the instant the drawer
 * closes. */
export function GlobalTrayDrawer() {
  const items = useTrayStore((s) => s.items);
  const chainMode = useTrayStore((s) => s.chainMode);
  const autoCut = useTrayStore((s) => s.autoCut);
  const lastAddedId = useTrayStore((s) => s.lastAddedId);
  const addItem = useTrayStore((s) => s.addItem);
  const current = useCurrentDesignStore((s) => s.current);
  const dialog = useDialogController();

  // Mirrors TrayPanel's own body derivation purely to summarize the header
  // button's own estimate suffix -- deliberately duplicated rather than
  // lifted into a shared context: identical usePrintEstimate inputs share
  // the same react-query cache entry, so this costs no extra request
  // beyond whatever TrayPanel itself already fetches while the drawer is
  // open.
  const trayHasItems = items.length > 0;
  const bodyLabels: LabelDefinition[] = trayHasItems
    ? items.map((i) => i.definition)
    : current !== null
      ? [current.definition]
      : [];
  const bodySerialization = trayHasItems || current === null ? null : current.serialization;
  const options: PrintOptions = { chain_mode: chainMode, margin_mm: 2.0, auto_cut: autoCut };

  function isRenderableBody(labels: LabelDefinition[]): boolean {
    if (trayHasItems) return labels.length > 0;
    if (current === null) return false;
    return labels.length === 1 && current.isRenderable(labels[0]!);
  }

  const { estimate } = usePrintEstimate(bodyLabels, options, isRenderableBody, bodySerialization);

  // The snapshot logic behind "+ Add to tray" -- moved here verbatim from
  // pages/Designer.tsx (pre-unification, task 2.12): a DEEP COPY of the
  // current design's definition, so editing the form afterward never
  // retroactively changes the queued item.
  function handleAddToTray() {
    if (!current || !current.canSubmit) return;
    addItem({
      definition: structuredClone(current.definition),
      png: current.png,
      lengthMm: current.lengthMm,
      label: current.label,
    });
  }

  // Rules of Hooks: every hook above must run on every render, so this
  // early return -- "hide entirely when there's nothing to act on" --
  // comes last, after them, not before.
  if (items.length === 0 && current === null) return null;

  const label = items.length === 0 ? "Tray" : `Tray · ${items.length}`;
  const suffix = estimate ? `, ${estimate.total_mm.toFixed(1)} mm` : "";

  return (
    <>
      <button
        type="button"
        onClick={dialog.open}
        aria-haspopup="dialog"
        className="rounded-md border border-deck-600 bg-deck-800 px-3 py-1.5 font-mono text-[12px] text-deck-200 transition-colors hover:border-deck-400"
      >
        {/* Brief "tick" on the count itself (stores/tray.ts's own
            `lastAddedId`, cleared 2s after an `addItem`) -- a plain
            transition-colors class swap fading amber -> deck-200, same
            mechanism/duration as TrayItemRow's own just-added highlight, so
            a user who adds from Homebox (or now, from the Designer page
            itself) sees the count itself acknowledge the add even before
            opening the drawer. */}
        <span className={`transition-colors ${lastAddedId !== null ? "text-amber-300" : ""}`}>{label}</span>
        {suffix}
      </button>

      {dialog.isOpen && <div aria-hidden onClick={dialog.close} className="fixed inset-0 z-40 bg-scrim/70" />}

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
        {/* `closeTrayDrawer={dialog.close}`: Track C2's own "Preview" button
            opens components/ChainPreviewDrawer.tsx, a SECOND right-edge
            slide-over -- see TrayPanel.tsx's own `closeTrayDrawer` prop doc
            for why this panel closes itself the instant that happens,
            rather than the two ever being visible stacked on top of each
            other. */}
        <TrayPanel current={current} onAddToTray={handleAddToTray} closeTrayDrawer={dialog.close} />
      </div>
    </>
  );
}
