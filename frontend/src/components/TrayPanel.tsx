import { useState } from "react";
import { usePrintEstimate } from "../hooks/usePrintEstimate";
import { usePrintJob } from "../hooks/usePrintJob";
import { useTrayPreviews } from "../hooks/useTrayPreviews";
import { usePrintPreviewStore } from "../stores/printPreview";
import type { CurrentDesign } from "../stores/currentDesign";
import { useTrayStore } from "../stores/tray";
import { CHAIN_MODE_OPTIONS } from "../lib/chainModes";
import { PrintButton } from "./PrintButton";
import { TrayItemRow } from "./TrayItemRow";
import { Pending } from "./ui/Pending";
import { SegmentedControl } from "./ui/SegmentedControl";
import { Switch } from "./ui/Switch";
import { dashedAddButtonClass, eyebrow, helpText } from "./ui/styles";
import type { LabelDefinition, PrintOptions } from "../api/types";

// Re-exported for compat: every existing import site/test wrote
// `import { TrayPanel, type CurrentDesign } from "./TrayPanel"` back when
// this file owned the type directly -- it now lives in
// stores/currentDesign.ts (stores must not import from components, and
// components/GlobalTrayDrawer.tsx needs it too), so this is the ONE place
// every consumer of the type keeps importing it from without a churn edit.
export type { CurrentDesign };

interface TrayPanelProps {
  current: CurrentDesign | null;
  /** Only meaningful (and only ever passed) when `current` is non-null --
   * there's nothing to add to the tray FROM when there's no current design
   * (GlobalTrayDrawer never passes this). */
  onAddToTray?: () => void;
  /** components/GlobalTrayDrawer.tsx's own `dialog.close` (hooks/
   * useDialogController.ts) -- passed down so THIS instance's "Preview
   * chain" button can close that slide-over the instant it opens
   * components/PrintPreviewDeck.tsx, since both occupy the right edge of
   * the viewport at once otherwise. Called synchronously, in the same
   * click handler, before stores/printPreview.ts's own `openDrawer()` --
   * `useDialogController`'s own `close()` moves focus back to
   * GlobalTrayDrawer's trigger ("Tray · N") synchronously too, which is
   * what lets PrintPreviewDeck's own open effect (document.activeElement
   * at the moment it opens) capture the RIGHT thing to restore focus to
   * later, instead of a button that's about to become invisible. Never
   * passed by JobTray.tsx (task 2.12's Designer-page sidebar/sheet) --
   * there's no sibling drawer of its own to close there, so the button
   * just opens PrintPreviewDeck directly. */
  closeTrayDrawer?: () => void;
}

function deltaText(deltaMm: number | null): string | null {
  if (deltaMm === null) return null;
  if (Math.abs(deltaMm) < 0.05) return "same tape usage as cut each";
  return deltaMm > 0 ? `saves ${deltaMm.toFixed(1)} mm vs cut each` : `uses ${Math.abs(deltaMm).toFixed(1)} mm more than cut each`;
}

/** The design doc's "JOB TRAY (sticky, estimate, chain mode, print)" -- the
 * tray's actual CONTENT (item list, chain mode/auto-cut, tape estimate,
 * print button + status line), extracted out of components/JobTray.tsx
 * (task 2.12) so it can be reused verbatim by components/GlobalTrayDrawer.tsx
 * (this task): the same tray, reachable from every OTHER route, has no
 * "current, unsaved design" of its own to fall back to -- `current` is
 * `null` there, and every current-design-specific affordance ("+ Add to
 * tray", the empty-tray-prints-the-current-design fallback) simply doesn't
 * render/apply in that case. JobTray.tsx keeps the Designer-only responsive
 * SHELL (sticky sidebar / mobile sheet) around this.
 *
 * Print semantics (unchanged from pre-extraction JobTray): an EMPTY tray
 * with a `current` design prints that design; a non-empty tray prints the
 * tray's own items instead (the current design is never silently included
 * -- it must be added first); an empty tray with `current === null` has
 * nothing to print at all. Mode/auto-cut apply to whichever body is
 * being printed, and drive both the live tape estimate and the actual
 * request so the number shown is always the number that would get used. */
export function TrayPanel({ current, onAddToTray, closeTrayDrawer }: TrayPanelProps) {
  const items = useTrayStore((s) => s.items);
  const chainMode = useTrayStore((s) => s.chainMode);
  const autoCut = useTrayStore((s) => s.autoCut);
  const lastAddedId = useTrayStore((s) => s.lastAddedId);
  const setChainMode = useTrayStore((s) => s.setChainMode);
  const setAutoCut = useTrayStore((s) => s.setAutoCut);
  const removeItem = useTrayStore((s) => s.removeItem);
  const duplicateItem = useTrayStore((s) => s.duplicateItem);
  const moveUp = useTrayStore((s) => s.moveUp);
  const moveDown = useTrayStore((s) => s.moveDown);
  const clearTray = useTrayStore((s) => s.clear);

  // Estimate details disclosure -- collapsed by default, extends
  // PrintPreviewDeck.tsx's own identical "Notes" disclosure pattern (see
  // that component's own comment above its button) to also hide the
  // Per-label/Content-overhead `<dl>`: the docked preview deck's own stats
  // column already shows those same numbers at a glance when it's open, so
  // permanently spending ~45px on a second copy here isn't worth it against
  // the xl rail's tight height budget -- see the disclosure's own comment
  // below for the measured numbers.
  const [detailsExpanded, setDetailsExpanded] = useState(false);

  // Track C2: components/PrintPreviewDeck.tsx's own open flag -- shared
  // (not local state) since that drawer mounts once, in AppShell.tsx, well
  // outside this component's own subtree. See that store's own docstring.
  const openChainPreview = usePrintPreviewStore((s) => s.openDrawer);

  // Items added with no captured preview (png: null, e.g. pages/Homebox.tsx's
  // "Add to tray") get one fetched here, keyed by item id -- see
  // hooks/useTrayPreviews.ts's own docstring.
  const previews = useTrayPreviews(items);

  const trayHasItems = items.length > 0;
  const trayFull = items.length >= 100; // POST /api/print's own `labels` max_length=100
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

  const canEstimate = trayHasItems || (current !== null && current.canSubmit);

  const { estimate, error, isFetching: estimateFetching } = usePrintEstimate(
    bodyLabels,
    options,
    isRenderableBody,
    bodySerialization,
  );

  // Chain-mode delta (the feature's whole point, per the brief): a SECOND,
  // independent estimate forced to cut_each -- chain_ff/strip_marks' own
  // TapeEstimate.notes don't carry this comparison (only cut_each's own
  // notes mention chaining, see render/estimate.py), so the UI fetches the
  // baseline itself rather than parsing prose. Skipped (isRenderableBody
  // gated off) when already on cut_each -- nothing to compare against.
  const needsBaseline = chainMode !== "cut_each";
  const baselineOptions: PrintOptions = { ...options, chain_mode: "cut_each" };
  const baseline = usePrintEstimate(
    bodyLabels,
    baselineOptions,
    (labels) => needsBaseline && isRenderableBody(labels),
    bodySerialization,
  );
  const delta = needsBaseline && estimate && baseline.estimate ? baseline.estimate.total_mm - estimate.total_mm : null;

  // Review fix-up: usePrintJob's own "done" state needs to know whether the
  // body it printed still matches what's on screen (see that hook's own
  // docstring) -- passed fresh every render, compared only against the
  // signature that was active at the LAST submit() call, never used to
  // fire anything itself.
  const bodyKey = JSON.stringify({ bodyLabels, options, bodySerialization });
  const job = usePrintJob(bodyKey);

  const blockedBySerializationAndTray = current !== null && current.serializationEnabled && trayHasItems;

  // Carry-forward fix (see CurrentDesign.serializationHasVisibleError's own
  // doc): a settled over-cap (or otherwise server-rejected) serialization
  // fires a genuine /api/print/estimate 422 too -- the SequenceEditor panel
  // already shows that exact message; defer to it instead of duplicating
  // the raw text a second time down here.
  const deferEstimateErrorToPanel = !trayHasItems && current !== null && current.serializationHasVisibleError && error !== null;

  return (
    <>
      <div className="flex items-center justify-between gap-2 xl:shrink-0">
        <span className={eyebrow}>Tray</span>
        {trayHasItems && (
          <button type="button" onClick={clearTray} className="text-[12px] text-deck-400 hover:text-deck-200">
            Clear
          </button>
        )}
      </div>

      {/* xl scroll contract: this is the ONLY region that scrolls at `xl` --
          the panel itself is `xl:overflow-hidden` (components/
          GlobalTrayDrawer.tsx's own open-gated class contract), and every
          sibling below (the fixed-controls block) is `xl:shrink-0`, so this
          is the sole flexible (`xl:flex-1 xl:min-h-0`) region left to absorb
          a long queue. Below `xl` it's a plain div -- the whole panel (or,
          below `xl`, the modal overlay) scrolls as one, unchanged. */}
      <div className="flex flex-col xl:min-h-0 xl:flex-1 xl:overflow-y-auto">
        {trayHasItems ? (
          <ul className="flex flex-col gap-2">
            {items.map((item, i) => (
              <TrayItemRow
                key={item.id}
                item={item}
                index={i}
                isFirst={i === 0}
                isLast={i === items.length - 1}
                onMoveUp={() => moveUp(item.id)}
                onMoveDown={() => moveDown(item.id)}
                onDuplicate={() => duplicateItem(item.id)}
                onRemove={() => removeItem(item.id)}
                hydratedPreview={previews.get(item.id)}
                justAdded={item.id === lastAddedId}
              />
            ))}
          </ul>
        ) : (
          <p className="text-[13px] text-deck-400">Nothing queued. Design a label and add it to print several at once.</p>
        )}
      </div>

      {/* Fixed controls: everything from "+ Add to tray" through the Print
          button stays pinned (`xl:shrink-0`) so the scroller above absorbs
          all the shrinking at `xl` -- with few items queued, this block
          simply sits anchored at the panel's bottom while the (now taller)
          scroller region grows to fill the gap. The nested `gap-4` mirrors
          the panel's own top-level `gap-4` so below-`xl` spacing between
          these controls is unchanged (`xl:gap-3` tightens it slightly AT
          xl only -- part of the same height-budget squeeze as the
          disclosure/Mode-description/Preview+Print changes below; measured
          live at 1440x900 with the deck docked: a 552px rail, ~135px of
          panel chrome, and this block landing around 437px collapsed the
          scroller to 0px -- these compactions bring it to roughly ~285px,
          leaving real room for the items list). */}
      <div className="flex flex-col gap-4 xl:gap-3 xl:shrink-0">
        {/* No "current design" to add FROM away from the Designer page --
            GlobalTrayDrawer never passes a `current`/`onAddToTray`, so this
            affordance simply doesn't render there. */}
        {current !== null && (
          <div className="flex flex-col items-start gap-1">
            <button
              type="button"
              onClick={onAddToTray}
              disabled={!current.canSubmit || trayFull}
              className={dashedAddButtonClass}
            >
              + Add to tray
            </button>
            {trayFull && <p className={helpText}>Tray is full (100 labels max).</p>}
          </div>
        )}

        <div className="border-t border-deck-800 pt-4">
          <span className={`${eyebrow} mb-1.5 block`}>Mode</span>
          <SegmentedControl ariaLabel="Mode" value={chainMode} options={CHAIN_MODE_OPTIONS} onChange={setChainMode} />
          {/* xl:hidden (height-budget squeeze): the relabeled options
              (SegmentedControl's own labels) are self-explanatory, and
              vertical space at xl is the items scroller's budget, not this
              description's -- stays visible below xl, where the whole panel
              scrolls as one and this costs nothing. */}
          <p className={`${helpText} xl:hidden`}>{CHAIN_MODE_OPTIONS.find((o) => o.value === chainMode)?.description}</p>
        </div>

        <Switch id="auto-cut" checked={autoCut} onChange={setAutoCut} label="Auto-cut" />

        <div className="rounded-lg border border-deck-700 bg-deck-800/40 p-3">
          <p className={eyebrow}>Tape estimate</p>
          {!canEstimate ? (
            <p className="mt-1.5 text-[12px] text-deck-400">Add content to estimate tape usage.</p>
          ) : deferEstimateErrorToPanel ? (
            <p className="mt-1.5 text-[12px] text-deck-400">Fix the serialization run in the Serialize panel to see a tape estimate.</p>
          ) : error ? (
            <p role="alert" className="mt-1.5 text-[12px] text-rust-500">
              {error}
            </p>
          ) : !estimate ? (
            <div className="mt-1.5">
              <Pending />
            </div>
          ) : (
            <>
              {/* data-testid: for a single-label body, "Per label" below is
                  numerically IDENTICAL to this total (total_mm / 1 label) --
                  a plain text query can't disambiguate the two in that (very
                  common) case, so both this and JobTray's own compact mobile
                  bar copy of the same total get stable testids/roles instead
                  of relying on unique text. */}
              <p data-testid="estimate-total-mm" className="mt-1.5 font-mono text-[20px] leading-none text-deck-200">
                {estimate.total_mm.toFixed(1)} mm
              </p>
              <div className="mt-2 flex h-2 w-full overflow-hidden rounded-full bg-deck-800" data-testid="estimate-usage-bar">
                <div
                  data-testid="estimate-usage-content"
                  className="h-full bg-amber-500"
                  style={{ width: `${estimate.total_mm > 0 ? (estimate.content_mm / estimate.total_mm) * 100 : 0}%` }}
                />
                <div
                  data-testid="estimate-usage-overhead"
                  className="h-full bg-deck-600"
                  style={{ width: `${estimate.total_mm > 0 ? (estimate.feed_overhead_mm / estimate.total_mm) * 100 : 0}%` }}
                />
              </div>
              {needsBaseline && (
                <p className="mt-2 font-mono text-[12px] text-amber-300">
                  {baseline.error
                    ? null
                    : baseline.estimate
                      ? deltaText(delta)
                      : (estimateFetching || baseline.isFetching) && <Pending />}
                </p>
              )}
              {/* Details disclosure -- collapsed by default at EVERY
                  breakpoint (not just xl), extending
                  components/PrintPreviewDeck.tsx's own identical "Notes"
                  disclosure pattern (see that component's own comment above
                  its button) to also hold the Per-label/Content-overhead
                  `<dl>`: the docked preview deck's own stats column already
                  shows those same numbers at a glance, so the tray's copy is
                  one click away instead of permanently spending ~45px here.
                  Total mm/usage bar above and the savings-delta line stay
                  unconditionally visible either way. `aria-label` gives this
                  button a distinct accessible name from the deck's own
                  "Notes" button -- both can be mounted at once
                  (GlobalTrayDrawer + PrintPreviewDeck both live in
                  AppShell.tsx). Renders whenever there's an estimate at all
                  (the dl is always there, unlike the notes ul below it,
                  which only renders when non-empty) -- button and region
                  always render together, so `aria-controls` never dangles. */}
              <button
                type="button"
                onClick={() => setDetailsExpanded((v) => !v)}
                aria-expanded={detailsExpanded}
                aria-controls="tray-estimate-details"
                aria-label="Estimate details"
                className="mt-2 flex items-center gap-1 self-start font-mono text-[11px] text-deck-400 transition-colors hover:text-deck-200"
              >
                Details <span aria-hidden="true">{detailsExpanded ? "▾" : "▸"}</span>
              </button>
              <div id="tray-estimate-details" hidden={!detailsExpanded}>
                <dl className="mt-2 flex flex-col gap-1 font-mono text-[13px] text-deck-200">
                  <div className="flex justify-between">
                    <dt className="text-deck-400">Per label</dt>
                    <dd>{estimate.per_label_mm.toFixed(1)} mm</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-deck-400">Content / overhead</dt>
                    <dd>
                      {estimate.content_mm.toFixed(1)} / {estimate.feed_overhead_mm.toFixed(1)} mm
                    </dd>
                  </div>
                </dl>
                {estimate.notes.length > 0 && (
                  <ul className="mt-2 flex flex-col gap-0.5 text-[11px] leading-snug text-deck-400">
                    {estimate.notes.map((note, i) => (
                      <li key={i}>· {note}</li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          )}
        </div>

        {/* Preview + Print share one row (height-budget squeeze, every
            breakpoint -- reads fine below xl too, not just at xl): Preview
            keeps its compact, content-sized width; PrintButton's own root
            is `w-full` internally (progress bar/success/error lines all
            want the full row), so it's wrapped in a `flex-1 min-w-0` div
            rather than edited itself, giving it the rest of the row instead
            of stretching the button element to match. */}
        <div className="flex items-center gap-2">
          {/* Track C2: opens components/PrintPreviewDeck.tsx, a wide preview
              deck composing the WHOLE tray body as one strip under whichever
              chain mode is currently selected -- the deck always previews the
              tray's own current Mode above (mode unification: a single source
              of truth, see PrintPreviewDeck.tsx's own docstring). UNLIKE the
              estimate panel/Print button below,
              this button previews the QUEUED JOB ONLY -- PrintPreviewDeck.tsx
              dropped its own current-design fallback entirely (see that
              component's own docstring), so `!trayHasItems` disables this one
              even while a current design makes `canEstimate` true (the
              empty-tray Print/estimate fallback itself is untouched). `!canEstimate`
              stays in the gate too for the ordinary "nothing valid at all"
              case. `closeTrayDrawer` (only ever set by GlobalTrayDrawer.tsx)
              runs FIRST -- see this button's own `closeTrayDrawer` prop doc for
              why the order matters. */}
          <button
            type="button"
            onClick={() => {
              closeTrayDrawer?.();
              openChainPreview();
            }}
            disabled={!trayHasItems || !canEstimate}
            aria-haspopup="dialog"
            className="rounded-md border border-deck-600 bg-deck-800 px-3 py-1.5 text-[13px] font-medium text-deck-200 transition-colors hover:border-deck-400 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Preview
          </button>

          {/* The block message renders exactly ONCE, inside PrintButton itself
              (its own role="alert") -- a second, standalone copy here would be
              the exact kind of duplicate-error surfacing this task's own
              carry-forward fix (see deferEstimateErrorToPanel above) exists to
              avoid. */}
          <div className="min-w-0 flex-1">
            <PrintButton
              job={job}
              labels={bodyLabels}
              options={options}
              serialization={bodySerialization}
              totalLabels={trayHasItems ? null : (current?.totalLabels ?? null)}
              isTray={trayHasItems}
              disabled={!canEstimate}
              blockedMessage={
                blockedBySerializationAndTray
                  ? "Turn off Serialize or clear the tray to print — a serialized run and a tray of designs can't be combined."
                  : null
              }
            />
          </div>
        </div>
      </div>
    </>
  );
}
