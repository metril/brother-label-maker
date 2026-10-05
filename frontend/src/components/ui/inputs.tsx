import { forwardRef, useEffect, useState } from "react";
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
  /** Defaults to "text". Settings.tsx's HomeBox API key field passes
   * "password" -- masks the value on-screen (a credential typed/pasted
   * into a visible plaintext box is otherwise shoulder-surfable, and
   * browsers/password managers treat "text" inputs as ordinary form
   * fields, not secrets). */
  type?: "text" | "password";
  /** Passed straight through to the underlying <input autocomplete=...>.
   * Settings.tsx's API key field sets "off" -- a credential this app never
   * even echoes back from the server shouldn't be offered for browser
   * autofill/autosave either. */
  autoComplete?: string;
}

/** forwardRef (task 2.11): components/schema/TokenInsertButtons.tsx needs
 * the underlying <input>'s own selectionStart/selectionEnd/setSelectionRange
 * to insert a `{seq}`/`{csv.<col>}` token at the cursor rather than always
 * appending to the end -- every other prop/behavior here is unchanged, and
 * every existing call site (this component takes no ref) still works
 * exactly as before. */
export const TextInput = forwardRef<HTMLInputElement, TextInputProps>(function TextInput(
  { id, value, onChange, placeholder, maxLength, ariaLabel, className, type = "text", autoComplete },
  ref,
) {
  return (
    <input
      ref={ref}
      id={id}
      type={type}
      value={value}
      placeholder={placeholder}
      maxLength={maxLength}
      aria-label={ariaLabel}
      autoComplete={autoComplete}
      onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
      className={className ?? textInputClass}
    />
  );
});

interface TextareaProps {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  rows?: number;
  maxLength?: number;
  ariaLabel?: string;
}

/** The List-kind Sequence editor's one-value-per-line control
 * (components/SequenceEditor.tsx) -- the only current caller, so styled
 * plainly rather than added to ui/styles.ts's shared class fragments. */
export function Textarea({ id, value, onChange, placeholder, rows = 5, maxLength, ariaLabel }: TextareaProps) {
  return (
    <textarea
      id={id}
      value={value}
      placeholder={placeholder}
      rows={rows}
      maxLength={maxLength}
      aria-label={ariaLabel}
      onChange={(e: ChangeEvent<HTMLTextAreaElement>) => onChange(e.target.value)}
      className="w-full resize-y rounded-md border border-deck-600 bg-deck-800 px-3 py-1.5 text-[14px] text-deck-200 placeholder:text-deck-400"
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
 * isn't.
 *
 * The chevron's own color must track the themed muted text color
 * (`--color-deck-400`), which a `background-image` data-URI can't do via
 * `currentColor` the way an inline `<svg>` can (a CSS background image is
 * resolved as its own independent document, outside this element's
 * inheritance chain) -- `var(--select-chevron)` instead references a CSS
 * custom property that index.css itself redeclares per theme (two
 * pre-rendered chevrons, one per theme's own deck-400 hex), the same
 * "redeclare in each theme block" mechanism every color in this app already
 * uses. See that file's own doc comment on `--select-chevron`. */
export function Select({ id, value, onChange, options, ariaLabel, disabled, className }: SelectProps) {
  return (
    <select
      id={id}
      value={value}
      disabled={disabled}
      aria-label={ariaLabel}
      onChange={(e) => onChange(e.target.value)}
      className={className ?? selectClass}
      style={{ backgroundImage: "var(--select-chevron)", backgroundRepeat: "no-repeat", backgroundPosition: "right 0.7rem center" }}
    >
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  );
}
