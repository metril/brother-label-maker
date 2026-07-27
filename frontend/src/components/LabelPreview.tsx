/** On-screen px per physical mm of TAPE WIDTH, for the constant-height
 * display band (24mm tape -> 96px tall band; 12mm -> 48px, per the task
 * brief). The image's on-screen WIDTH is never computed from this -- the
 * <img> is given a fixed height and `width: "auto"`, so the browser scales
 * width from the PNG's own natural aspect ratio. This sidesteps the preview
 * endpoint's unit trap entirely: width_px/height_px (scaled device dots)
 * never enter this component at all, only the decoded image's own pixels
 * and the physical `length_mm` readout below it. */
const BAND_PX_PER_MM = 4;

interface LabelPreviewProps {
  tapeWidthMm: number;
  hasContent: boolean;
  png: string | null;
  lengthMm: number | null;
  warnings: string[];
  isFetching: boolean;
  error: string | null;
}

export function LabelPreview({
  tapeWidthMm,
  hasContent,
  png,
  lengthMm,
  warnings,
  isFetching,
  error,
}: LabelPreviewProps) {
  const bandHeightPx = tapeWidthMm * BAND_PX_PER_MM;

  return (
    <div className="flex flex-col items-center gap-3">
      <div className="flex min-h-[140px] w-full items-center justify-center rounded-lg border border-ink-700 bg-ink-900 p-8">
        {error ? (
          <div role="alert" className="max-w-sm text-center text-sm text-red-400">
            {error}
          </div>
        ) : !hasContent ? (
          <p className="text-sm text-ink-500">Type something to preview your label.</p>
        ) : !png ? (
          <div
            role="status"
            aria-label="Loading preview"
            className="shimmer rounded-sm"
            style={{ height: bandHeightPx, width: Math.max(bandHeightPx * 2, 80) }}
          />
        ) : (
          <div className="relative">
            <img
              src={png}
              alt="Label preview"
              style={{ height: bandHeightPx, width: "auto", imageRendering: "pixelated" }}
              className="rounded-sm bg-white shadow-[0_2px_10px_rgba(0,0,0,0.5)]"
            />
            {isFetching && (
              <div
                aria-hidden
                data-testid="preview-refreshing"
                className="pointer-events-none absolute inset-0 animate-pulse rounded-sm bg-ink-950/10"
              />
            )}
          </div>
        )}
      </div>

      <div className="flex flex-col items-center gap-2">
        <p className="font-mono text-sm text-ink-300">
          {lengthMm != null ? `${lengthMm.toFixed(1)} mm` : "—"}
        </p>
        {warnings.length > 0 && (
          <ul className="flex flex-wrap justify-center gap-1.5">
            {warnings.map((warning) => (
              <li
                key={warning}
                className="rounded-full border border-amber-600/50 bg-amber-950 px-2 py-0.5 text-[11px] text-amber-300"
              >
                {warning}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
