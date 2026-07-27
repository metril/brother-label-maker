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
  value: number;
  onChange: (value: number) => void;
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
 * user mid-keystroke. */
export function NumberInput({ id, value, onChange, min, max, step, ariaLabel, className }: NumberInputProps) {
  return (
    <input
      id={id}
      type="number"
      value={Number.isNaN(value) ? "" : value}
      min={min}
      max={max}
      step={step ?? "any"}
      aria-label={ariaLabel}
      onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.valueAsNumber)}
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

export function Select({ id, value, onChange, options, ariaLabel, disabled, className }: SelectProps) {
  return (
    <select
      id={id}
      value={value}
      disabled={disabled}
      aria-label={ariaLabel}
      onChange={(e) => onChange(e.target.value)}
      className={className ?? selectClass}
    >
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  );
}
