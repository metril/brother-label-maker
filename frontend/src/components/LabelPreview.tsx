import type { RenderWarning } from "../api/types";

/** On-screen px per physical mm, applied to the image's WIDTH from
 * `lengthMm` directly (never to height first) -- height is then left to
 * `"auto"`, so the browser derives it from the PNG's own natural aspect
 * ratio. Deriving the OTHER way around (fix height from nominal tape
 * width, let width auto-follow the image's raw pixel ratio) is wrong: the
 * PNG's pixel height is the printable strip (tape.print_dots, e.g. 128
 * dots / ~18mm for 24mm TZe tape -- driver/geometry.py's _TZE_ROWS), not
 * the nominal tape width (24mm, which includes unprintable margin either
 * side). Fixing a 24mm-tall band onto an 18mm-tall image stretches BOTH
 * axes by ~24/18 (~33%) to fill it -- inflating the on-screen LENGTH the
 * same amount. Anchoring on `lengthMm` (the backend's physical truth, same
 * field the text readout below uses) instead sidesteps that mismatch
 * entirely, and keeps this component's only unit-trap-relevant input as
 * `lengthMm` -- it never reads png_width_px/png_height_px (scaled device
 * dots) at all. */
const PX_PER_MM = 4;

interface LabelPreviewProps {
  tapeWidthMm: number;
  hasContent: boolean;
  png: string | null;
  lengthMm: number | null;
  warnings: RenderWarning[];
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
  // Only used for the loading shimmer's placeholder size, before a
  // `lengthMm` is even known -- doesn't need to be physically exact, it's
  // a loading indicator, not a rendering of the label itself.
  const shimmerHeightPx = tapeWidthMm * PX_PER_MM;

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
            style={{ height: shimmerHeightPx, width: Math.max(shimmerHeightPx * 2, 80) }}
          />
        ) : (
          <div className="relative">
            <img
              src={png}
              alt="Label preview"
              style={{
                width: lengthMm != null ? lengthMm * PX_PER_MM : undefined,
                height: "auto",
                imageRendering: "pixelated",
              }}
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
            {warnings.map((warning, index) => (
              <li
                key={`${warning.code}:${index}`}
                className={
                  warning.severity === "warning"
                    ? "rounded-full border border-amber-600/50 bg-amber-950 px-2 py-0.5 text-[11px] text-amber-300"
                    : "rounded-full border border-ink-600/50 bg-ink-800 px-2 py-0.5 text-[11px] text-ink-400"
                }
              >
                {warning.message}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
