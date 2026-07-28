import { useRef } from "react";
import type { JsonSchemaObject } from "../../schema/jsonSchema";
import { TextInput } from "../ui/inputs";
import { dashedAddButtonClass, fieldLabelText, helpText, iconButtonClass, indexBadge } from "../ui/styles";
import { TokenInsertButtons } from "./TokenInsertButtons";

interface ArrayOfStringsProps {
  label: string;
  help?: string;
  schema: JsonSchemaObject;
  value: string[];
  onChange: (value: string[]) => void;
}

let uidCounter = 0;
function newRowUid(): string {
  uidCounter += 1;
  return `line-${uidCounter}`;
}

/** Repeatable text rows -- text.lines, cable_wrap/cable_flag.lines,
 * punch_down.extra_lines, terminal_block.labels, and (recursively, one
 * level down) each divided-blocks row's own `lines`. Add/remove/reorder via
 * buttons, never drag-only (WCAG 2.5.7) -- 1-based index shown in mono
 * (matching the 1-based row aria-labels below, not a raw 0-based array
 * index), bounds from minItems/maxItems enforced by disabling the buttons
 * that would violate them rather than a post-hoc error message.
 *
 * Rows are keyed by a stable per-row uid (`keysRef`), not their current
 * array index -- see ArrayOfObjects.tsx's own identical `keysRef` for why:
 * an index-keyed row's DOM (and any focus within it) doesn't MOVE when the
 * row reorders, only its rendered content does, so a focused "move down"
 * button silently starts acting on a different row after one swap. */
export function ArrayOfStrings({ label, help, schema, value, onChange }: ArrayOfStringsProps) {
  const minItems = schema.minItems ?? 0;
  const maxItems = schema.maxItems;
  const itemMaxLength = schema.items?.maxLength;
  const atMax = maxItems !== undefined && value.length >= maxItems;
  const keysRef = useRef<string[]>(value.map(() => newRowUid()));

  if (keysRef.current.length !== value.length) {
    keysRef.current = value.map((_, i) => keysRef.current[i] ?? newRowUid());
  }

  function setItem(i: number, next: string) {
    onChange(value.map((item, idx) => (idx === i ? next : item)));
  }
  function addItem() {
    if (atMax) return;
    keysRef.current = [...keysRef.current, newRowUid()];
    onChange([...value, ""]);
  }
  function removeItem(i: number) {
    if (value.length <= minItems) return;
    keysRef.current = keysRef.current.filter((_, idx) => idx !== i);
    onChange(value.filter((_, idx) => idx !== i));
  }
  function move(i: number, dir: -1 | 1) {
    const j = i + dir;
    if (j < 0 || j >= value.length) return;

    const nextKeys = [...keysRef.current];
    const tmpKey = nextKeys[i]!;
    nextKeys[i] = nextKeys[j]!;
    nextKeys[j] = tmpKey;
    keysRef.current = nextKeys;

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
        <StringRow
          key={keysRef.current[i]}
          label={label}
          index={i}
          value={item}
          itemMaxLength={itemMaxLength}
          onChange={(v) => setItem(i, v)}
          onMoveUp={() => move(i, -1)}
          onMoveDown={() => move(i, 1)}
          onRemove={() => removeItem(i)}
          canMoveUp={i > 0}
          canMoveDown={i < value.length - 1}
          canRemove={value.length > minItems}
        />
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

interface StringRowProps {
  label: string;
  index: number;
  value: string;
  itemMaxLength?: number;
  onChange: (value: string) => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onRemove: () => void;
  canMoveUp: boolean;
  canMoveDown: boolean;
  canRemove: boolean;
}

/** One repeatable-row's input + its own move/remove buttons + (task 2.11)
 * its own token-insert affordance -- split out from the array's own render
 * loop so each row can own a stable ref to its <input> (TokenInsertButtons
 * needs the DOM node's own selectionStart/selectionEnd to insert a token
 * at the cursor, not just append to the end). */
function StringRow({
  label,
  index,
  value,
  itemMaxLength,
  onChange,
  onMoveUp,
  onMoveDown,
  onRemove,
  canMoveUp,
  canMoveDown,
  canRemove,
}: StringRowProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const rowLabel = `${label} ${index + 1}`;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <span className={indexBadge}>{index + 1}</span>
        <TextInput ref={inputRef} value={value} ariaLabel={rowLabel} maxLength={itemMaxLength} onChange={onChange} />
        <div className="flex shrink-0 gap-1">
          <button type="button" aria-label={`Move ${rowLabel} up`} disabled={!canMoveUp} onClick={onMoveUp} className={iconButtonClass}>
            ↑
          </button>
          <button
            type="button"
            aria-label={`Move ${rowLabel} down`}
            disabled={!canMoveDown}
            onClick={onMoveDown}
            className={iconButtonClass}
          >
            ↓
          </button>
          <button type="button" aria-label={`Remove ${rowLabel}`} disabled={!canRemove} onClick={onRemove} className={iconButtonClass}>
            ×
          </button>
        </div>
      </div>
      <TokenInsertButtons inputRef={inputRef} value={value} onChange={onChange} fieldLabel={rowLabel} className="pl-8" />
    </div>
  );
}
