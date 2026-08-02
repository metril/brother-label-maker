import { usePrintEstimate } from "../hooks/usePrintEstimate";
import { usePrintJob } from "../hooks/usePrintJob";
import { useTrayPreviews } from "../hooks/useTrayPreviews";
import { useTrayStore } from "../stores/tray";
import { PrintButton } from "./PrintButton";
import { TrayItemRow } from "./TrayItemRow";
import { Checkbox } from "./ui/inputs";
import { Pending } from "./ui/Pending";
import { SegmentedControl } from "./ui/SegmentedControl";
import { dashedAddButtonClass, eyebrow, helpText } from "./ui/styles";
import type { ChainMode, LabelDefinition, PrintOptions, Sequence } from "../api/types";

// Plain-language descriptions per the design doc's copy voice ("what the
// user gets, not protocol jargon"). chain_ff/strip_marks' underlying tape
// math is UNVERIFIED until the physical checkpoint (see backend/render/
// estimate.py's own module docstring) -- that caveat stays in code
// comments only, never in this user-facing copy.
const CHAIN_MODE_OPTIONS: { value: ChainMode; label: string; description: string }[] = [
  { value: "cut_each", label: "Cut each", description: "Every label cut separately. Most tape used." },
  // UNVERIFIED until checkpoint 2.
  { value: "chain_ff", label: "Chain", description: "Printed end to end, one cut at the end. Saves tape." },
  // UNVERIFIED until checkpoint 2.
  { value: "strip_marks", label: "One strip", description: "Single strip with printed guides. Cut them yourself." },
];

/** The "current, unsaved design" half of what the tray can print -- built by
 * pages/Designer.tsx (which owns the schema/params/preview this is derived
 * from) and handed down as one bundle rather than half a dozen loose props.
 * `null` away from the Designer page (components/GlobalTrayDrawer.tsx) --
 * there is no such design to fall back to or add from on any other route,
 * see TrayPanelProps' own doc. */
export interface CurrentDesign {
  definition: LabelDefinition;
  /** Strict "safe to submit THIS right now" gate -- content present, every
   * number field in bounds, and (if serialization is on) the run confirmed
   * printable. Mirrors what Designer.tsx used to compute as its own
   * `jobTrayCanSubmit` pre-2.12. */
  canSubmit: boolean;
  /** The debounce-safe predicate (schema/renderable.ts + numberValidity.ts)
   * applied to a single definition -- used to gate usePrintEstimate's
   * network call the same "match the debounced value, not the live one"
   * way usePreview.ts already does (see that hook's own docstring). */
  isRenderable: (definition: LabelDefinition) => boolean;
  png: string | null;
  lengthMm: number | null;
  /** "Type + first text line" -- what a tray item added FROM this design
   * would be captioned (lib/tray.ts's describeCurrentDesign). */
  label: string;
  serializationEnabled: boolean;
  /** The confirmed serialization spec, or null (off, or not yet confirmed
   * printable) -- see Designer.tsx's own `activeSerialization`. */
  serialization: Sequence | null;
  totalLabels: number | null;
  /** True while the Serialize panel (components/SequenceEditor.tsx) is
   * ALREADY showing its own error for the current settled sequence (e.g. a
   * total-labels-over-1000 422) -- carry-forward fix: lets the tray's
   * estimate panel defer to that instead of re-printing the identical raw
   * server message a second time (see the estimate-error branch below). */
  serializationHasVisibleError: boolean;
}

interface TrayPanelProps {
  current: CurrentDesign | null;
  /** Only meaningful (and only ever passed) when `current` is non-null --
   * there's nothing to add to the tray FROM when there's no current design
   * (GlobalTrayDrawer never passes this). */
  onAddToTray?: () => void;
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
 * nothing to print at all. Chain mode/auto-cut apply to whichever body is
 * being printed, and drive both the live tape estimate and the actual
 * request so the number shown is always the number that would get used. */
export function TrayPanel({ current, onAddToTray }: TrayPanelProps) {
  const items = useTrayStore((s) => s.items);
  const chainMode = useTrayStore((s) => s.chainMode);
  const autoCut = useTrayStore((s) => s.autoCut);
  const setChainMode = useTrayStore((s) => s.setChainMode);
  const setAutoCut = useTrayStore((s) => s.setAutoCut);
  const removeItem = useTrayStore((s) => s.removeItem);
  const duplicateItem = useTrayStore((s) => s.duplicateItem);
  const moveUp = useTrayStore((s) => s.moveUp);
  const moveDown = useTrayStore((s) => s.moveDown);
  const clearTray = useTrayStore((s) => s.clear);

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
      <div className="flex items-center justify-between gap-2">
        <span className={eyebrow}>Tray</span>
        {trayHasItems && (
          <button type="button" onClick={clearTray} className="text-[12px] text-deck-400 hover:text-deck-200">
            Clear
          </button>
        )}
      </div>

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
            />
          ))}
        </ul>
      ) : (
        <p className="text-[13px] text-deck-400">Nothing queued. Design a label and add it to print several at once.</p>
      )}

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
        <span className={`${eyebrow} mb-1.5 block`}>Chain mode</span>
        <SegmentedControl ariaLabel="Chain mode" value={chainMode} options={CHAIN_MODE_OPTIONS} onChange={setChainMode} />
        <p className={helpText}>{CHAIN_MODE_OPTIONS.find((o) => o.value === chainMode)?.description}</p>
      </div>

      <Checkbox id="auto-cut" checked={autoCut} onChange={setAutoCut} label="Auto-cut" />

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
            {needsBaseline && (
              <p className="mt-2 font-mono text-[12px] text-amber-300">
                {baseline.error
                  ? null
                  : baseline.estimate
                    ? deltaText(delta)
                    : (estimateFetching || baseline.isFetching) && <Pending />}
              </p>
            )}
            {estimate.notes.length > 0 && (
              <ul className="mt-2 flex flex-col gap-0.5 text-[11px] leading-snug text-deck-400">
                {estimate.notes.map((note, i) => (
                  <li key={i}>· {note}</li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>

      {/* The block message renders exactly ONCE, inside PrintButton itself
          (its own role="alert") -- a second, standalone copy here would be
          the exact kind of duplicate-error surfacing this task's own
          carry-forward fix (see deferEstimateErrorToPanel above) exists to
          avoid. */}
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
    </>
  );
}
