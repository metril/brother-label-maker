import { useTapes } from "../hooks/useTapes";

interface TapeSelectorProps {
  valueMm: number;
  onChange: (widthMm: number) => void;
}

/** TZe tape width picker, driven by GET /api/tapes (backend/driver/
 * geometry.py's all_tapes() is the single source of truth -- this used to
 * be a hardcoded TZE_WIDTHS_MM list here, a drift risk B2 removed) filtered
 * to family "tze" to keep the exact same UX as before: the six TZe
 * widths, nothing else. */
export function TapeSelector({ valueMm, onChange }: TapeSelectorProps) {
  const { data: tapes, isPending } = useTapes();

  if (isPending || !tapes) {
    return (
      <div role="group" aria-label="Tape width" className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled
          aria-label="Loading tape widths"
          className="shimmer h-8 w-64 rounded-md border border-ink-700"
        />
      </div>
    );
  }

  const tzeTapes = tapes.filter((tape) => tape.family === "tze");

  return (
    <div role="group" aria-label="Tape width" className="flex flex-wrap gap-2">
      {tzeTapes.map((tape) => {
        const selected = tape.nominal_mm === valueMm;
        return (
          <button
            key={tape.nominal_mm}
            type="button"
            aria-pressed={selected}
            onClick={() => onChange(tape.nominal_mm)}
            className={`rounded-md border px-3 py-1.5 text-sm font-medium transition-colors ${
              selected
                ? "border-amber-500 bg-amber-950 text-amber-300"
                : "border-ink-600 bg-ink-800 text-ink-200 hover:border-ink-500 hover:text-ink-100"
            }`}
          >
            {tape.nominal_mm}mm
          </button>
        );
      })}
    </div>
  );
}
