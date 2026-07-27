import { segmentedButtonClass } from "./styles";

interface Option<T extends string> {
  value: T;
  label: string;
}

interface SegmentedControlProps<T extends string> {
  ariaLabel: string;
  options: Option<T>[];
  value: T;
  onChange: (value: T) => void;
}

/** A small button group standing in for a native `<select>` when there are
 * few enough options to show them all at once (used for booleans-as-modes,
 * auto/manual toggles, and short string enums) -- role="radiogroup" per
 * ARIA's radio-button pattern, arrow-key navigable like a real radio group. */
export function SegmentedControl<T extends string>({
  ariaLabel,
  options,
  value,
  onChange,
}: SegmentedControlProps<T>) {
  function handleKeyDown(event: React.KeyboardEvent, index: number) {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    const delta = event.key === "ArrowRight" ? 1 : -1;
    const next = options[(index + delta + options.length) % options.length];
    if (next) onChange(next.value);
  }

  return (
    <div role="radiogroup" aria-label={ariaLabel} className="flex flex-wrap gap-1.5">
      {options.map((opt, index) => (
        <button
          key={opt.value}
          type="button"
          role="radio"
          aria-checked={value === opt.value}
          tabIndex={value === opt.value ? 0 : -1}
          onKeyDown={(e) => handleKeyDown(e, index)}
          onClick={() => onChange(opt.value)}
          className={segmentedButtonClass(value === opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
