import { TZE_WIDTHS_MM } from "../stores/designer";

interface TapeSelectorProps {
  valueMm: number;
  onChange: (widthMm: number) => void;
}

/** TZe tape width picker. The six widths MUST match the backend's geometry
 * table (backend/driver/geometry.py's _TZE_ROWS) -- see TZE_WIDTHS_MM. */
export function TapeSelector({ valueMm, onChange }: TapeSelectorProps) {
  return (
    <div role="group" aria-label="Tape width" className="flex flex-wrap gap-2">
      {TZE_WIDTHS_MM.map((mm) => {
        const selected = mm === valueMm;
        return (
          <button
            key={mm}
            type="button"
            aria-pressed={selected}
            onClick={() => onChange(mm)}
            className={`rounded-md border px-3 py-1.5 text-sm font-medium transition-colors ${
              selected
                ? "border-amber-500 bg-amber-950 text-amber-300"
                : "border-ink-600 bg-ink-800 text-ink-200 hover:border-ink-500 hover:text-ink-100"
            }`}
          >
            {mm}mm
          </button>
        );
      })}
    </div>
  );
}
