interface SwitchProps {
  id?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  disabled?: boolean;
}

/** A toggle for boolean settings ("no checkboxes for settings" -- the
 * design brief's own call): `role="switch"` + `aria-checked` (not a native
 * `<input type=checkbox>`) is the correct ARIA widget for an on/off SETTING
 * that takes effect immediately, as distinct from a `role="checkbox"`
 * multi-select item in a list (see ui/styles.ts's `checkboxClass`, used by
 * HomeboxEntityRow.tsx/pages/Homebox.tsx's own raw checkboxes, which keep
 * that different semantic on purpose). A plain `<button>` gives Space/Enter
 * activation and focus for free -- no extra key handling needed.
 *
 * Wrapped in a `<label htmlFor={id}>` exactly like ui/inputs.tsx's Checkbox
 * (its label element is not `id`-conditional -- clicking anywhere in the
 * row, including the visible text, forwards a click to this button per the
 * HTML label-association spec, since `button` is itself a labelable
 * element) -- so the accessible name/click target stay identical to what
 * Checkbox produced at every replaced call site, only the role changes.
 *
 * The thumb's `translate-x` swap is a `transition-transform`, not a CSS
 * `@keyframes` animation -- index.css's own `prefers-reduced-motion: reduce`
 * block zeroes out `transition-duration` globally, so this is disabled for
 * free under that setting rather than needing its own escape hatch. */
export function Switch({ id, checked, onChange, label, disabled }: SwitchProps) {
  return (
    <label htmlFor={id} className="flex items-center gap-2 text-[14px] text-deck-200">
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border px-0.5 transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
          checked ? "border-amber-500 bg-amber-500" : "border-deck-600 bg-deck-800"
        }`}
      >
        <span
          aria-hidden="true"
          className={`h-4 w-4 rounded-full transition-transform ${
            checked ? "translate-x-4 bg-deck-950" : "translate-x-0 bg-deck-200"
          }`}
        />
      </button>
      {label}
    </label>
  );
}
