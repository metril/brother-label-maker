import type { RenderWarning, Tape, TapeInfo } from "../api/types";
import { computeFeedDeckGeometry, formatMm, PX_PER_MM } from "../lib/feedDeckGeometry";
import { Pending } from "./ui/Pending";
import { iconButtonClass } from "./ui/styles";

export interface SequenceStepperProps {
  /** 0-based, into the FULL expanded run (copies_per_value/collation
   * already applied -- see backend/render/serialize.py's ordered_values). */
  index: number;
  total: number;
  /** The sequence value that produced the CURRENTLY rendered preview at
   * `index` -- from POST /api/render/preview's own `sequence_value` (see
   * api/types.ts's PreviewResponse doc), not re-derived client-side. */
  sequenceValue: string | null;
  onIndexChange: (index: number) => void;
}

interface FeedDeckProps {
  tape: Tape;
  /** The matching /api/tapes row for `tape` (nominal_mm+family exact
   * match) -- null while /api/tapes is still loading (brief, staleTime:
   * Infinity) or, in principle, for a tape combination the catalog
   * doesn't have. */
  tapeInfo: TapeInfo | null;
  /** Whether the CURRENT params have enough required content to preview at
   * all (schema/renderable.ts's hasRenderableContent) -- deliberately the
   * LOOSE gate, not "is it safe to actually send a request right now"
   * (Designer.tsx's stricter canSubmit, which also requires every number
   * field in bounds). Everything below -- the deck strip itself, the
   * length readout, the warning chips -- is gated on THIS prop, and only
   * this prop: `png`/`lengthMm`/`warnings` come from a react-query cache
   * that can otherwise hold stale data from before the user cleared the
   * form, or from a DIFFERENT label type entirely (switching types keeps
   * this same component mounted) -- gating strictly on `hasContent`
   * (synchronous, derived fresh from the current params every render,
   * never stale) is what stops a blank form or a freshly-switched type
   * from showing a contradictory leftover "10.0 mm" readout above a "Type
   * something to preview your label." message. A numeric field being
   * transiently out of bounds does NOT flip hasContent false, so the deck
   * correctly keeps showing the last successful render in that case
   * instead ("keep the last good preview" -- see Designer.tsx's canSubmit
   * split and usePreview.ts's query gating). */
  hasContent: boolean;
  png: string | null;
  lengthMm: number | null;
  minFeedMm: number | null;
  warnings: RenderWarning[];
  isFetching: boolean;
  error: string | null;
  /** Warning chips with an `object_id` (e.g. "block-3") call this to
   * focus/highlight the matching form row -- see Designer.tsx. */
  onFocusObject?: (objectId: string) => void;
  /** task 2.11: "when serialization is on, the feed deck gains a compact
   * stepper" (brief) -- null/omitted for the plain (non-serialized) path,
   * which renders exactly as before. Owned by pages/Designer.tsx (the
   * index itself is UI-only state that drives usePreview's own `index`
   * argument), not this component -- FeedDeck stays presentational. */
  sequenceStepper?: SequenceStepperProps | null;
  /** track C3: on-screen px-per-physical-mm, overriding
   * feedDeckGeometry.ts's DEFAULT_PX_PER_MM -- the Designer page's own
   * zoom control (2x/4x/8x) owns this state and passes it down; omitted
   * (undefined) renders at the same default size as before this track.
   * FeedDeck stays presentational: it neither owns nor renders the zoom
   * control itself, only threads the resulting value into the geometry. */
  pxPerMm?: number;
}

/** The feed deck: the design system's signature element (see the design
 * doc's "Signature element" section). Renders the tape's true physical
 * geometry -- strip proportion from length_mm and the tape's nominal
 * width, the printable band inset from /api/tapes' print_mm, a cut line at
 * the label's end, and a hatched minimum-feed-waste region when the label
 * is shorter than the mechanical feed floor -- never from the preview
 * PNG's own pixel dimensions (see feedDeckGeometry.ts's PX_PER_MM doc).
 * The previous image stays on screen while a new one loads (no flash) --
 * `isFetching` only ever adds a subtle overlay, never clears `png`. */
export function FeedDeck({
  tape,
  tapeInfo,
  hasContent,
  png,
  lengthMm,
  minFeedMm,
  warnings,
  isFetching,
  error,
  onFocusObject,
  sequenceStepper,
  pxPerMm,
}: FeedDeckProps) {
  const warningList = warnings.filter((w) => w.severity === "warning");
  const infoList = warnings.filter((w) => w.severity === "info");
  const ready = png !== null && tapeInfo !== null && lengthMm !== null && minFeedMm !== null;
  // Everything derived (length readout, warning chips) is shown only when
  // there's real, current content AND no error -- see hasContent's own
  // docstring above for why this specific gate (not "is `lengthMm` set")
  // is what keeps a stale/cross-type readout from ever appearing next to
  // an empty-state or error message.
  const showDerived = hasContent && !error;

  return (
    <div className="flex flex-col gap-3">
      {sequenceStepper && (
        <div className="flex flex-wrap items-center gap-2 font-mono text-[13px] text-deck-200">
          <button
            type="button"
            aria-label="Previous label"
            disabled={sequenceStepper.index <= 0}
            onClick={() => sequenceStepper.onIndexChange(Math.max(0, sequenceStepper.index - 1))}
            className={iconButtonClass}
          >
            ◀
          </button>
          <span>
            {sequenceStepper.index + 1} / {sequenceStepper.total}
          </span>
          <button
            type="button"
            aria-label="Next label"
            disabled={sequenceStepper.index >= sequenceStepper.total - 1}
            onClick={() => sequenceStepper.onIndexChange(Math.min(sequenceStepper.total - 1, sequenceStepper.index + 1))}
            className={iconButtonClass}
          >
            ▶
          </button>
          {sequenceStepper.sequenceValue && (
            <span className="rounded-full border border-amber-500/50 bg-amber-500/10 px-2.5 py-1 text-[11px] text-amber-300">
              {sequenceStepper.sequenceValue}
            </span>
          )}
        </div>
      )}
      <div className="relative overflow-x-auto rounded-xl border border-deck-700 bg-deck-900 px-6 py-8">
        {error ? (
          <div role="alert" className="max-w-sm text-[13px] text-rust-500">
            {error}
          </div>
        ) : !hasContent ? (
          <p className="text-[13px] text-deck-400">Type something to preview your label.</p>
        ) : !ready ? (
          <div
            role="status"
            aria-label="Loading preview"
            className="flex min-w-[120px] items-center justify-center"
            style={{ height: tape.width_mm * (pxPerMm ?? PX_PER_MM) }}
          >
            <Pending />
          </div>
        ) : (
          <DeckStrip
            png={png}
            lengthMm={lengthMm}
            nominalMm={tape.width_mm}
            printMm={tapeInfo.print_mm}
            minFeedMm={minFeedMm}
            isFetching={isFetching}
            pxPerMm={pxPerMm}
          />
        )}
      </div>

      {showDerived && lengthMm !== null && (
        <p className="font-mono text-[20px] leading-none text-deck-200">{lengthMm.toFixed(1)} mm</p>
      )}

      {showDerived && (warningList.length > 0 || infoList.length > 0) && (
        <div className="flex flex-col gap-1.5">
          {warningList.length > 0 && <WarningChipRow warnings={warningList} tone="warning" onFocusObject={onFocusObject} />}
          {infoList.length > 0 && <WarningChipRow warnings={infoList} tone="info" onFocusObject={onFocusObject} />}
        </div>
      )}
    </div>
  );
}

interface DeckStripProps {
  png: string;
  lengthMm: number;
  nominalMm: number;
  printMm: number;
  minFeedMm: number;
  isFetching: boolean;
  /** track C3: overrides feedDeckGeometry.ts's DEFAULT_PX_PER_MM. Omitted
   * by the Gallery page (task 2.14's call site), which must keep rendering
   * at the same default size it always has -- only Designer's FeedDeck
   * usage ever passes a non-default value. */
  pxPerMm?: number;
}

/** Exported for the Gallery page (task 2.14), which renders the same strip
 * per card -- one geometry implementation (computeFeedDeckGeometry), two
 * call sites, zero duplication. */
export function DeckStrip({ png, lengthMm, nominalMm, printMm, minFeedMm, isFetching, pxPerMm }: DeckStripProps) {
  const geo = computeFeedDeckGeometry(lengthMm, nominalMm, printMm, minFeedMm, pxPerMm);

  return (
    <div className="inline-flex flex-col items-start gap-2">
      <div className="relative" style={{ width: geo.totalWidthPx, height: geo.stripHeightPx }}>
        {/* The tape strip -- the one place true light appears (--color-tape).
            The hairline border is mostly for the light theme: --color-tape
            is a fixed off-white in BOTH themes, so on a white light-theme
            panel it would otherwise have no visible edge at all -- harmless
            (barely visible) in the dark theme, where the tape already reads
            clearly against the darker panel behind it. */}
        <div
          data-testid="printable-band"
          className="absolute inset-y-0 left-0 overflow-hidden rounded-[2px] border border-deck-600/50 shadow-[0_1px_4px_rgba(0,0,0,0.4)]"
          style={{ width: geo.stripWidthPx, backgroundColor: "var(--color-tape)" }}
        >
          {/* Unprintable margins, top and bottom -- a FIXED dark tint
              (--color-tape-margin) at low opacity OVER the tape, per the
              design doc: subtly darker, not a different color entirely, so
              it still reads as "tape". Deliberately not a themed neutral
              like --color-deck-200 (which flips light/dark between themes,
              and would make this margin read completely differently
              depending which theme happened to be active) -- see
              index.css's own doc on --color-tape-margin. */}
          <div
            aria-hidden
            className="absolute inset-x-0 top-0"
            style={{ height: geo.marginHeightPx, backgroundColor: "var(--color-tape-margin)", opacity: 0.35 }}
          />
          <div
            aria-hidden
            className="absolute inset-x-0 bottom-0"
            style={{ height: geo.marginHeightPx, backgroundColor: "var(--color-tape-margin)", opacity: 0.35 }}
          />
          {/* The rendered content, sized from PHYSICAL mm on both axes
              (never png_width_px/png_height_px) and inset into exactly the
              printable band. */}
          <img
            src={png}
            alt="Label preview"
            style={{
              position: "absolute",
              left: 0,
              top: geo.marginHeightPx,
              width: geo.stripWidthPx,
              height: geo.printableHeightPx,
              imageRendering: "pixelated",
            }}
          />
          {isFetching && (
            <div
              aria-hidden
              data-testid="preview-refreshing"
              className="pointer-events-none absolute inset-0 animate-pulse bg-scrim/10"
            />
          )}
        </div>

        {/* Cut line -- a hairline dashed rust rule at the label's end. */}
        <div
          aria-hidden
          data-testid="cut-line"
          className="absolute inset-y-0"
          style={{ left: geo.cutLineXPx, borderLeft: "1.5px dashed var(--color-rust-500)" }}
        />

        {/* Minimum-feed shadow: tape that still gets fed through, unprinted. */}
        {geo.feedWasteWidthPx > 0 && (
          <div
            aria-label={`${geo.feedWasteMm.toFixed(1)} mm feed waste`}
            data-testid="feed-waste"
            className="absolute inset-y-0"
            style={{
              left: geo.stripWidthPx,
              width: geo.feedWasteWidthPx,
              backgroundColor: "var(--color-deck-700)",
              backgroundImage:
                "repeating-linear-gradient(45deg, transparent, transparent 3px, var(--color-deck-600) 3px, var(--color-deck-600) 6px)",
            }}
          />
        )}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-0.5 font-mono text-[11px] text-deck-400">
        <span>
          {formatMm(printMm)} mm printable of {formatMm(nominalMm)} mm
        </span>
        {geo.feedWasteMm > 0 && <span>+{geo.feedWasteMm.toFixed(1)} mm feed waste</span>}
      </div>
    </div>
  );
}

/** Exported for the Gallery page alongside DeckStrip -- same chips, same
 * severity split, no per-page restyling. */
export function WarningChipRow({
  warnings,
  tone,
  onFocusObject,
}: {
  warnings: RenderWarning[];
  tone: "warning" | "info";
  onFocusObject?: (objectId: string) => void;
}) {
  const chipClass =
    tone === "warning"
      ? "rounded-full border border-amber-500/50 bg-amber-500/10 px-2.5 py-1 text-[11px] text-amber-300"
      : "rounded-full border border-deck-600 bg-deck-800 px-2.5 py-1 text-[11px] text-deck-400";

  return (
    <ul className="flex flex-wrap gap-1.5">
      {warnings.map((w, i) => (
        <li key={`${w.code}:${i}`}>
          {w.object_id && onFocusObject ? (
            <button
              type="button"
              onClick={() => onFocusObject(w.object_id!)}
              className={`${chipClass} cursor-pointer hover:border-amber-300`}
            >
              {w.message}
            </button>
          ) : (
            <span className={chipClass}>{w.message}</span>
          )}
        </li>
      ))}
    </ul>
  );
}
