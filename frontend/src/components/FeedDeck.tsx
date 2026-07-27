import type { RenderWarning, Tape, TapeInfo } from "../api/types";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import { computeFeedDeckGeometry, formatMm, PX_PER_MM } from "../lib/feedDeckGeometry";
import { Pending } from "./ui/Pending";

interface FeedDeckProps {
  tape: Tape;
  /** The matching /api/tapes row for `tape` (nominal_mm+family exact
   * match) -- null while /api/tapes is still loading (brief, staleTime:
   * Infinity) or, in principle, for a tape combination the catalog
   * doesn't have. */
  tapeInfo: TapeInfo | null;
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
}: FeedDeckProps) {
  const reducedMotion = usePrefersReducedMotion();
  const warningList = warnings.filter((w) => w.severity === "warning");
  const infoList = warnings.filter((w) => w.severity === "info");
  const ready = png !== null && tapeInfo !== null && lengthMm !== null && minFeedMm !== null;

  return (
    <div className="flex flex-col gap-3">
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
            style={{ height: tape.width_mm * PX_PER_MM }}
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
            reducedMotion={reducedMotion}
          />
        )}
      </div>

      {lengthMm !== null && <p className="font-mono text-[20px] leading-none text-deck-200">{lengthMm.toFixed(1)} mm</p>}

      {(warningList.length > 0 || infoList.length > 0) && (
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
  reducedMotion: boolean;
}

function DeckStrip({ png, lengthMm, nominalMm, printMm, minFeedMm, isFetching }: DeckStripProps) {
  const geo = computeFeedDeckGeometry(lengthMm, nominalMm, printMm, minFeedMm);

  return (
    <div className="inline-flex flex-col items-start gap-2">
      <div className="relative" style={{ width: geo.totalWidthPx, height: geo.stripHeightPx }}>
        {/* The tape strip -- the one place true light appears (--color-tape). */}
        <div
          className="absolute inset-y-0 left-0 overflow-hidden rounded-[2px] shadow-[0_1px_4px_rgba(0,0,0,0.4)]"
          style={{ width: geo.stripWidthPx, backgroundColor: "var(--color-tape)" }}
        >
          {/* Unprintable margins, top and bottom -- deck-200 at low opacity
              OVER the tape, per the design doc: subtly darker, not a
              different color entirely, so it still reads as "tape". */}
          <div
            aria-hidden
            className="absolute inset-x-0 top-0"
            style={{ height: geo.marginHeightPx, backgroundColor: "var(--color-deck-200)", opacity: 0.35 }}
          />
          <div
            aria-hidden
            className="absolute inset-x-0 bottom-0"
            style={{ height: geo.marginHeightPx, backgroundColor: "var(--color-deck-200)", opacity: 0.35 }}
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
              className="pointer-events-none absolute inset-0 animate-pulse bg-deck-950/10"
            />
          )}
        </div>

        {/* Cut line -- a hairline dashed rust rule at the label's end. */}
        <div
          aria-hidden
          className="absolute inset-y-0"
          style={{ left: geo.cutLineXPx, borderLeft: "1.5px dashed var(--color-rust-500)" }}
        />

        {/* Minimum-feed shadow: tape that still gets fed through, unprinted. */}
        {geo.feedWasteWidthPx > 0 && (
          <div
            aria-label={`${geo.feedWasteMm.toFixed(1)} mm feed waste`}
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

function WarningChipRow({
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
              className={`${chipClass} cursor-pointer hover:border-amber-400`}
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
