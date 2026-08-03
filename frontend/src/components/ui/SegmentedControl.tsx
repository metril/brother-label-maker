import { useRef } from "react";
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
 * ARIA's radio-button pattern, arrow-key navigable like a real radio group.
 *
 * Roving tabindex (only the checked option is in the Tab order, everything
 * else is -1) means arrow-key navigation MUST move real DOM focus itself,
 * not just call `onChange` -- otherwise focus is stranded on whichever
 * button the user originally tabbed to (now `tabIndex={-1}` the instant
 * selection moves off it), and every subsequent arrow press keeps
 * recomputing `index` from that same stale button, making anything past
 * the immediate neighbor keyboard-unreachable (M9 review fix). `buttonRefs`
 * exists solely to call `.focus()` on the new selection alongside
 * `onChange`. */
export function SegmentedControl<T extends string>({
  ariaLabel,
  options,
  value,
  onChange,
}: SegmentedControlProps<T>) {
  const buttonRefs = useRef<(HTMLButtonElement | null)[]>([]);

  function selectAndFocus(index: number) {
    const next = options[index];
    if (!next) return;
    onChange(next.value);
    buttonRefs.current[index]?.focus();
  }

  function handleKeyDown(event: React.KeyboardEvent, index: number) {
    switch (event.key) {
      // Right/Down and Left/Up are equivalent per the ARIA radiogroup
      // pattern (https://www.w3.org/WAI/ARIA/apg/patterns/radio/) -- same
      // wrap-around semantics as before (mod options.length), unchanged.
      case "ArrowRight":
      case "ArrowDown":
        event.preventDefault();
        selectAndFocus((index + 1) % options.length);
        return;
      case "ArrowLeft":
      case "ArrowUp":
        event.preventDefault();
        selectAndFocus((index - 1 + options.length) % options.length);
        return;
      case "Home":
        event.preventDefault();
        selectAndFocus(0);
        return;
      case "End":
        event.preventDefault();
        selectAndFocus(options.length - 1);
        return;
      default:
        return;
    }
  }

  return (
    <div role="radiogroup" aria-label={ariaLabel} className="flex flex-wrap gap-1.5">
      {options.map((opt, index) => (
        <button
          key={opt.value}
          ref={(el) => {
            buttonRefs.current[index] = el;
          }}
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
