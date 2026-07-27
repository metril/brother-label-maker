import type { JsonSchemaObject } from "../../schema/jsonSchema";
import { TextInput } from "../ui/inputs";
import { dashedAddButtonClass, fieldLabelText, helpText, iconButtonClass, indexBadge } from "../ui/styles";

interface ArrayOfStringsProps {
  label: string;
  help?: string;
  schema: JsonSchemaObject;
  value: string[];
  onChange: (value: string[]) => void;
}

/** Repeatable text rows -- text.lines, cable_wrap/cable_flag.lines,
 * punch_down.extra_lines, terminal_block.labels, and (recursively, one
 * level down) each divided-blocks row's own `lines`. Add/remove/reorder via
 * buttons, never drag-only (WCAG 2.5.7) -- index shown in mono, bounds from
 * minItems/maxItems enforced by disabling the buttons that would violate
 * them rather than a post-hoc error message. */
export function ArrayOfStrings({ label, help, schema, value, onChange }: ArrayOfStringsProps) {
  const minItems = schema.minItems ?? 0;
  const maxItems = schema.maxItems;
  const itemMaxLength = schema.items?.maxLength;
  const atMax = maxItems !== undefined && value.length >= maxItems;

  function setItem(i: number, next: string) {
    onChange(value.map((item, idx) => (idx === i ? next : item)));
  }
  function addItem() {
    if (atMax) return;
    onChange([...value, ""]);
  }
  function removeItem(i: number) {
    if (value.length <= minItems) return;
    onChange(value.filter((_, idx) => idx !== i));
  }
  function move(i: number, dir: -1 | 1) {
    const j = i + dir;
    if (j < 0 || j >= value.length) return;
    const next = [...value];
    const tmp = next[i]!;
    next[i] = next[j]!;
    next[j] = tmp;
    onChange(next);
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
          <span className={indexBadge}>{i}</span>
          <TextInput
            value={item}
            ariaLabel={`${label} ${i + 1}`}
            maxLength={itemMaxLength}
            onChange={(v) => setItem(i, v)}
          />
          <div className="flex shrink-0 gap-1">
            <button
              type="button"
              aria-label={`Move ${label} ${i + 1} up`}
              disabled={i === 0}
              onClick={() => move(i, -1)}
              className={iconButtonClass}
            >
              ↑
            </button>
            <button
              type="button"
              aria-label={`Move ${label} ${i + 1} down`}
              disabled={i === value.length - 1}
              onClick={() => move(i, 1)}
              className={iconButtonClass}
            >
              ↓
            </button>
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
