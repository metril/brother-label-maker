import { useEffect, useState } from "react";
import type { ChangeEvent } from "react";
import { numberInputClass, selectClass, textInputClass } from "./styles";

interface TextInputProps {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  maxLength?: number;
  ariaLabel?: string;
  className?: string;
}

export function TextInput({ id, value, onChange, placeholder, maxLength, ariaLabel, className }: TextInputProps) {
  return (
    <input
      id={id}
      type="text"
      value={value}
      placeholder={placeholder}
      maxLength={maxLength}
      aria-label={ariaLabel}
      onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
      className={className ?? textInputClass}
    />
  );
}

interface NumberInputProps {
  id?: string;
  /** `undefined` means "empty" -- a genuinely cleared field, not a
   * coerced 0. Callers own what an empty field MEANS for their own params
   * (see SchemaField.tsx's number case): this component's only job is to
   * never fight the user mid-edit by snapping back to some other number
   * while they're typing/backspacing. */
  value: number | undefined;
  onChange: (value: number | undefined) => void;
  min?: number;
  max?: number;
  step?: number;
  ariaLabel?: string;
  className?: string;
}

/** Numbers are always JetBrains Mono in this app ("every measurement and
 * machine value") -- numberInputClass carries that. `min`/`max`/`step` are
 * the schema's own Field bounds where present (see schema/jsonSchema.ts) --
 * HTML enforcement (spinner clamping) plus the caller's own inline
 * out-of-bounds message, never a silent clamp-on-type that fights the
 * user mid-keystroke.
 *
 * Keeps its OWN local text buffer (`raw`), not just `String(value)` on
 * every render: a native `<input type=number>` bound straight to a
 * `value: number` prop can't represent "the box is empty right now" (there
 * is no such number) or "-"/"1." (not yet a complete number) -- either
 * would get silently coerced to some other number every keystroke,
 * fighting a user backspacing "15" down to nothing. `raw` only resyncs
 * FROM `value` when they've actually diverged (a real external change,
 * e.g. a preset load or switching label types) -- never on the render
 * immediately following this component's own onChange, which would just
 * echo the same edit back and clobber an in-progress "-"/"1." keystroke. */
export function NumberInput({ id, value, onChange, min, max, step, ariaLabel, className }: NumberInputProps) {
  const [raw, setRaw] = useState(() => (value === undefined ? "" : String(value)));

  useEffect(() => {
    const parsedRaw = raw === "" ? undefined : Number(raw);
    const rawAlreadyMatches = parsedRaw === value || (Number.isNaN(parsedRaw) && value === undefined);
    if (!rawAlreadyMatches) {
      setRaw(value === undefined ? "" : String(value));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return (
    <input
      id={id}
      type="number"
      value={raw}
      min={min}
      max={max}
      step={step ?? "any"}
      aria-label={ariaLabel}
      onChange={(e: ChangeEvent<HTMLInputElement>) => {
        const next = e.target.value;
        setRaw(next);
        const parsed = e.target.valueAsNumber;
        onChange(next === "" || Number.isNaN(parsed) ? undefined : parsed);
      }}
      className={className ?? numberInputClass}
    />
  );
}

interface CheckboxProps {
  id?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
}

export function Checkbox({ id, checked, onChange, label }: CheckboxProps) {
  return (
    <label htmlFor={id} className="flex items-center gap-2 text-[14px] text-deck-200">
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 rounded border-deck-600 bg-deck-800 accent-amber-500"
      />
      {label}
    </label>
  );
}

interface SelectOption {
  value: string;
  label: string;
}

interface SelectProps {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  ariaLabel?: string;
  disabled?: boolean;
  className?: string;
}

/** A small chevron background image gives the native <select> a dropdown
 * affordance -- with `appearance-none` (selectClass) removing the browser's
 * own inconsistent-looking arrow, nothing otherwise distinguished a select
 * from a plain text input at a glance. Inline `style` (not a Tailwind
 * arbitrary-value class) because escaping a data-URI SVG through Tailwind's
 * own bracket-notation quoting is fragile; a plain CSS background-image
 * isn't. */
const CHEVRON_BACKGROUND =
  "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6' fill='none'%3E%3Cpath d='M1 1L5 5L9 1' stroke='%238A7E6E' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E\")";

export function Select({ id, value, onChange, options, ariaLabel, disabled, className }: SelectProps) {
  return (
    <select
      id={id}
      value={value}
      disabled={disabled}
      aria-label={ariaLabel}
      onChange={(e) => onChange(e.target.value)}
      className={className ?? selectClass}
      style={{ backgroundImage: CHEVRON_BACKGROUND, backgroundRepeat: "no-repeat", backgroundPosition: "right 0.7rem center" }}
    >
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  );
}
