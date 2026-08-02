import { useEffect, useState } from "react";
import type { RefObject } from "react";
import { pngDataUrl } from "../api/client";
import { useChainedPreview } from "../hooks/useChainedPreview";
import { CHAIN_MODE_OPTIONS } from "../lib/chainModes";
import { DEFAULT_PX_PER_MM } from "../lib/feedDeckGeometry";
import { Dialog } from "./ui/Dialog";
import { Pending } from "./ui/Pending";
import { SegmentedControl } from "./ui/SegmentedControl";
import { errorText, eyebrow, helpText, iconButtonClass } from "./ui/styles";
import type { ChainMode, LabelDefinition, PrintOptions, Sequence } from "../api/types";

interface ChainedPreviewDialogProps {
  open: boolean;
  onClose: () => void;
  closeButtonRef: RefObject<HTMLButtonElement | null>;
  labels: LabelDefinition[];
  /** The tray's own submit-time options (margin_mm/auto_cut) -- `chain_mode`
   * is never read off this directly, only from this dialog's OWN local
   * `mode` state below (see `initialChainMode`, which just seeds it). */
  options: PrintOptions;
  serialization: Sequence | null;
  /** The same "is there enough to actually render" predicate TrayPanel
   * already computes for its own estimate query (isRenderableBody) --
   * reused as-is rather than re-derived here. */
  isRenderable: (labels: LabelDefinition[]) => boolean;
  /** The tray's chain mode AT THE MOMENT this dialog opens -- seeds this
   * dialog's own local mode tabs (see the effect below) and nothing else:
   * flipping between modes in here is a "what would this look like"
   * comparison, not a tray edit, so it never writes back to
   * useTrayStore's own chainMode/setChainMode. */
  initialChainMode: ChainMode;
}

/** track C3-style zoom control, mirrored (not imported -- pages/Designer.tsx
 * doesn't export these) from that page's own preview-zoom convention
 * (commit 0566dcf): the option's own string IS the px-per-mm figure
 * (`Number(zoom)` below), "4" matches feedDeckGeometry.ts's own
 * DEFAULT_PX_PER_MM so the strip opens at that same default size. */
type ZoomLevel = "2" | "4" | "8";
const ZOOM_OPTIONS: { value: ZoomLevel; label: string }[] = [
  { value: "2", label: "2×" },
  { value: "4", label: "4×" },
  { value: "8", label: "8×" },
];

/** Track C2: a wide dialog previewing the WHOLE chained job as a single
 * composited strip -- POST /api/print/preview's own png_b64, sized and
 * annotated purely from its `segments` (mm offsets along the strip), never
 * from the PNG's own pixel dimensions (see api/types.ts's
 * ChainedPreviewResponse UNIT TRAP doc and lib/feedDeckGeometry.ts's own
 * docstring, whose DEFAULT_PX_PER_MM this reuses rather than re-deriving a
 * second scale constant).
 *
 * The estimator this preview's stats row summarizes is UNVERIFIED pending
 * the physical print checkpoint (see backend/render/estimate.py's own
 * module docstring) -- that caveat is repeated here in user-facing copy,
 * same as TrayPanel's own tape-estimate panel already does in its code
 * comments only; this dialog is the first place it becomes visible to the
 * user directly, so it's spelled out plainly rather than left implicit. */
export function ChainedPreviewDialog({
  open,
  onClose,
  closeButtonRef,
  labels,
  options,
  serialization,
  isRenderable,
  initialChainMode,
}: ChainedPreviewDialogProps) {
  const [mode, setMode] = useState<ChainMode>(initialChainMode);
  // DEFAULT_PX_PER_MM (4) as the dialog's opening zoom level -- reusing the
  // SAME constant feedDeckGeometry.ts's own "never derive mm from PNG
  // pixels" contract is built on (see this file's own UNIT TRAP note
  // above), rather than a second, independently-chosen default.
  const [zoom, setZoom] = useState<ZoomLevel>(String(DEFAULT_PX_PER_MM) as ZoomLevel);

  // Re-seed `mode` from the tray's own chain mode every time the dialog
  // OPENS -- guarded on `open` alone (not `initialChainMode`) so a tab the
  // user already clicked is never clobbered by a re-render while the
  // dialog stays open. The tray sits behind this modal's own backdrop
  // while open (clicks on it are captured by the backdrop, same as every
  // other dialog in this app), so `initialChainMode` genuinely can't
  // change out from under an in-progress comparison anyway.
  useEffect(() => {
    if (open) setMode(initialChainMode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const previewOptions: PrintOptions = { ...options, chain_mode: mode };
  const { preview, isFetching, error } = useChainedPreview(labels, previewOptions, isRenderable, serialization, open);

  const pxPerMm = Number(zoom);
  // All labels in a body share one tape (server-validated, see
  // router_print.py's _validate_and_measure) -- the nominal tape width is
  // therefore the same read off any one of them.
  const tapeWidthMm = labels[0]?.tape.width_mm ?? 0;
  const lastSegment = preview && preview.segments.length > 0 ? preview.segments[preview.segments.length - 1]! : null;
  // UNIT TRAP (see ChainedPreviewResponse's own doc): the composite PNG's
  // own drawn content ends at the LAST segment's end_mm, NOT at
  // `preview.total_mm` -- total_mm additionally counts feed overhead
  // (margins, the trailing cut/feed allowance) that's never actually
  // painted into the image, so sizing the strip from it would stretch the
  // image past its own real content.
  const contentWidthMm = lastSegment?.end_mm ?? 0;
  const stripWidthPx = contentWidthMm * pxPerMm;
  const stripHeightPx = tapeWidthMm * pxPerMm;

  const renderable = isRenderable(labels);

  return (
    <Dialog open={open} onClose={onClose} label="Chain preview" className="max-w-4xl">
      <div className="flex items-center justify-between gap-2">
        <span className={eyebrow}>Chain preview</span>
        <button
          type="button"
          ref={closeButtonRef}
          onClick={onClose}
          aria-label="Close chain preview"
          className={iconButtonClass}
        >
          ×
        </button>
      </div>

      <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <div>
          <span className={`${eyebrow} mb-1.5 block`}>Chain mode</span>
          <SegmentedControl ariaLabel="Preview chain mode" value={mode} options={CHAIN_MODE_OPTIONS} onChange={setMode} />
          <p className={helpText}>{CHAIN_MODE_OPTIONS.find((o) => o.value === mode)?.description}</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-[11px] text-deck-400">Zoom</span>
          <SegmentedControl ariaLabel="Preview zoom" options={ZOOM_OPTIONS} value={zoom} onChange={setZoom} />
        </div>
      </div>

      <div className="mt-4">
        {!renderable ? (
          <p className="text-[13px] text-deck-400">Nothing to preview.</p>
        ) : error ? (
          <p role="alert" className={errorText}>
            {error}
          </p>
        ) : !preview ? (
          <div className="flex min-h-[120px] items-center justify-center">
            <Pending />
          </div>
        ) : (
          <>
            <div className="relative overflow-x-auto rounded-xl border border-deck-700 bg-deck-900 px-6 py-8">
              <div className="relative" style={{ width: stripWidthPx, height: stripHeightPx }}>
                <img
                  src={pngDataUrl(preview.png_b64)}
                  alt="Chained job preview"
                  style={{ width: stripWidthPx, height: stripHeightPx, imageRendering: "pixelated" }}
                />
                {preview.segments.map((seg) => (
                  <span key={seg.index}>
                    <span
                      data-testid={`segment-chip-${seg.index}`}
                      className="absolute top-1 rounded-full border border-amber-500/50 bg-deck-900/80 px-1.5 py-0.5 font-mono text-[10px] leading-none text-amber-300"
                      style={{ left: seg.start_mm * pxPerMm + 4 }}
                    >
                      {seg.index + 1}
                    </span>
                    {/* Dashed cut-boundary line at this label's own end --
                        same visual convention as FeedDeck's own cut-line
                        (DeckStrip's cutLineXPx), one per segment so a
                        multi-label strip shows every boundary, not just
                        the composite's overall end. */}
                    <span
                      aria-hidden
                      data-testid={`segment-boundary-${seg.index}`}
                      className="absolute inset-y-0"
                      style={{ left: seg.end_mm * pxPerMm, borderLeft: "1.5px dashed var(--color-rust-500)" }}
                    />
                  </span>
                ))}
                {isFetching && (
                  <span aria-hidden className="pointer-events-none absolute inset-0 block animate-pulse bg-scrim/10" />
                )}
              </div>
            </div>

            <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 font-mono text-[13px] text-deck-200">
              <div className="flex flex-col">
                <dt className="text-[11px] text-deck-400">Total</dt>
                <dd data-testid="preview-total-mm">{preview.total_mm.toFixed(1)} mm</dd>
              </div>
              <div className="flex flex-col">
                <dt className="text-[11px] text-deck-400">Content / overhead</dt>
                <dd>
                  {preview.content_mm.toFixed(1)} / {preview.feed_overhead_mm.toFixed(1)} mm
                </dd>
              </div>
              <div className="flex flex-col">
                <dt className="text-[11px] text-deck-400">Per label</dt>
                <dd>{preview.per_label_mm.toFixed(1)} mm</dd>
              </div>
            </dl>

            {preview.notes.length > 0 && (
              <ul className="mt-2 flex flex-col gap-0.5 text-[11px] leading-snug text-deck-400">
                {preview.notes.map((note, i) => (
                  <li key={i}>· {note}</li>
                ))}
              </ul>
            )}

            {preview.warnings.length > 0 && (
              <ul className="mt-2 flex flex-col gap-1">
                {preview.warnings.map((w, i) => (
                  <li key={i} role="alert" className="text-[12px] text-rust-500">
                    {w}
                  </li>
                ))}
              </ul>
            )}

            <p className={helpText}>
              Tape usage shown here is an UNVERIFIED estimate pending the physical print checkpoint — actual
              feed/margin behavior on real hardware may differ.
            </p>
          </>
        )}
      </div>
    </Dialog>
  );
}
