import type { JsonSchemaObject } from "../../schema/jsonSchema";
import { NumberInput } from "../ui/inputs";
import { dashedAddButtonClass, fieldLabelText, helpText, iconButtonClass, indexBadge } from "../ui/styles";

interface ArrayOfNumbersProps {
  label: string;
  help?: string;
  schema: JsonSchemaObject;
  /** An item can be `undefined` -- a genuinely cleared row, not a coerced 0
   * -- same convention as MultipliersField's own `(number | undefined)[]`,
   * see that component's `setItem`. */
  value: (number | undefined)[];
  onChange: (value: (number | undefined)[]) => void;
}

/** Generic repeatable-number-rows fallback -- same add/remove/reorder shape
 * as ArrayOfStrings. patch_panel's `multipliers` (the one nullable
 * array-of-number field across the 9 types) gets a bespoke override
 * (MultipliersField, linked to `blocks.length`) instead of this generic
 * path -- this exists so the schema-driven engine still degrades sensibly
 * if a future label type adds another one without its own override. */
export function ArrayOfNumbers({ label, help, schema, value, onChange }: ArrayOfNumbersProps) {
  const minItems = schema.minItems ?? 0;
  const maxItems = schema.maxItems;
  const min = schema.items?.minimum;
  const max = schema.items?.maximum;
  const atMax = maxItems !== undefined && value.length >= maxItems;

  function setItem(i: number, next: number | undefined) {
    // `next` can genuinely be `undefined` (a cleared row) -- propagate it
    // into params rather than swallowing it. The old `if (next ===
    // undefined) return;` here left the BOX empty (NumberInput's own local
    // text buffer, see ui/inputs.tsx) while `value` -- and therefore
    // numberValidity's hasNumberOutOfRange walk -- still held the stale
    // pre-clear number, so nothing gated submission on what the user was
    // actually looking at. Mirrors MultipliersField.setItem, which never
    // had this bug.
    onChange(value.map((item, idx) => (idx === i ? next : item)));
  }
  function addItem() {
    if (atMax) return;
    onChange([...value, min ?? 0]);
  }
  function removeItem(i: number) {
    if (value.length <= minItems) return;
    onChange(value.filter((_, idx) => idx !== i));
  }

  return (
    <fieldset className="flex flex-col gap-2">
      <legend className={fieldLabelText}>
        {label}{" "}
        <span className="font-mono text-deck-400">
          ({value.length}
          {maxItems !== undefined ? `/${maxItems}` : ""})
        </span>
      </legend>
      {help && <p className={`${helpText} -mt-1 mb-1`}>{help}</p>}
      {value.map((item, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className={indexBadge}>{i + 1}</span>
          <NumberInput value={item} min={min} max={max} ariaLabel={`${label} ${i + 1}`} onChange={(v) => setItem(i, v)} />
          <button
            type="button"
            aria-label={`Remove ${label} ${i + 1}`}
            disabled={value.length <= minItems}
            onClick={() => removeItem(i)}
            className={iconButtonClass}
          >
            ×
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={addItem}
        disabled={atMax}
        aria-label={`Add ${label} row`}
        className={dashedAddButtonClass}
      >
        + Add
      </button>
    </fieldset>
  );
}
