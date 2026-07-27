import { useRef } from "react";
import { buildItemDefault } from "../../schema/defaults";
import { singularize } from "../../schema/humanize";
import { resolveRef, type JsonSchemaObject } from "../../schema/jsonSchema";
import type { PathSegment } from "../../schema/paths";
import { dashedAddButtonClass, fieldLabelText, helpText, iconButtonClass, indexBadge } from "../ui/styles";
import { useHighlighted } from "./HighlightContext";
import { SchemaField } from "./SchemaField";

interface ArrayOfObjectsProps {
  label: string;
  help?: string;
  /** The ARRAY schema itself (has .items, .minItems, .maxItems). */
  schema: JsonSchemaObject;
  root: JsonSchemaObject;
  value: Record<string, unknown>[];
  onChange: (value: Record<string, unknown>[]) => void;
  path: PathSegment[];
}

let uidCounter = 0;
function newRowUid(): string {
  uidCounter += 1;
  return `row-${uidCounter}`;
}

/** Repeatable groups -- patch_panel/faceplate's `blocks`, breaker_box's
 * `breakers`. Each row recursively renders its own item schema's
 * properties via SchemaField (so BreakerSpec's `poles` number field and
 * `lines` array-of-strings both just work, no breaker_box-specific code
 * here). Every row's DOM id is `block-{index}` regardless of the field's
 * own name -- that's the exact `object_id` divided_blocks.py's own
 * RenderWarnings use (see render/types/divided_blocks.py), so a warning
 * chip's "focus this row" click resolves correctly whether the array is
 * called `blocks` or `breakers`.
 *
 * Rows are keyed by a STABLE per-row uid (`keysRef`, assigned once when a
 * row is created and carried along through add/remove/reorder), NOT by
 * their current array index. Keying by index made keyboard reorder a
 * near-no-op past one swap: React reconciles same-key elements as "the
 * same DOM node, just moved", so a stable key is what actually MOVES a
 * row's DOM (and therefore keyboard focus) to its new position along with
 * the data -- keyed by index instead, the DOM node at each position stayed
 * put while its CONTENT swapped underneath it, so a focused "move down"
 * button kept acting on whatever row now happened to render at that same
 * position rather than the row the user actually meant. */
export function ArrayOfObjects({ label, help, schema, root, value, onChange, path }: ArrayOfObjectsProps) {
  const minItems = schema.minItems ?? 0;
  const maxItems = schema.maxItems;
  const itemSchema = resolveRef(schema.items ?? {}, root);
  const atMax = maxItems !== undefined && value.length >= maxItems;
  const keysRef = useRef<string[]>(value.map(() => newRowUid()));

  // Keep keysRef in lockstep positionally with `value` -- our own
  // addItem/removeItem/move below mutate both together for user-driven
  // changes; this guards against `value` changing length from OUTSIDE this
  // component entirely (a preset load, switching label types) by assigning
  // fresh uids for any new tail positions rather than losing sync.
  if (keysRef.current.length !== value.length) {
    keysRef.current = value.map((_, i) => keysRef.current[i] ?? newRowUid());
  }

  function updateItem(i: number, next: Record<string, unknown>) {
    onChange(value.map((item, idx) => (idx === i ? next : item)));
  }
  function addItem() {
    if (atMax) return;
    keysRef.current = [...keysRef.current, newRowUid()];
    onChange([...value, buildItemDefault(schema.items ?? {}, root) as Record<string, unknown>]);
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

  const rowPrefixBase = singularize(label);

  return (
    <fieldset className="flex flex-col gap-3">
      <legend className={fieldLabelText}>
        {label}{" "}
        <span className="font-mono text-deck-400">
          ({value.length}
          {maxItems !== undefined ? `/${maxItems}` : ""})
        </span>
      </legend>
      {help && <p className={`${helpText} -mt-1 mb-1`}>{help}</p>}
      {value.map((item, i) => (
        <BlockRow
          key={keysRef.current[i]}
          index={i}
          rowLabel={label}
          labelPrefix={`${rowPrefixBase} ${i + 1}`}
          item={item}
          itemSchema={itemSchema}
          root={root}
          path={[...path, i]}
          onChange={(next) => updateItem(i, next)}
          onRemove={() => removeItem(i)}
          onMoveUp={() => move(i, -1)}
          onMoveDown={() => move(i, 1)}
          canRemove={value.length > minItems}
          isFirst={i === 0}
          isLast={i === value.length - 1}
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

interface BlockRowProps {
  index: number;
  rowLabel: string;
  /** "Block 1", "Breaker 2" -- threaded into this row's own nested
   * SchemaField calls so a repeated field name (e.g. every block's own
   * "Lines") gets a row-qualified, unique accessible name instead of
   * colliding across rows (see SchemaFieldProps.labelPrefix). */
  labelPrefix: string;
  item: Record<string, unknown>;
  itemSchema: JsonSchemaObject;
  root: JsonSchemaObject;
  path: PathSegment[];
  onChange: (next: Record<string, unknown>) => void;
  onRemove: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  canRemove: boolean;
  isFirst: boolean;
  isLast: boolean;
}

function BlockRow({
  index,
  rowLabel,
  labelPrefix,
  item,
  itemSchema,
  root,
  path,
  onChange,
  onRemove,
  onMoveUp,
  onMoveDown,
  canRemove,
  isFirst,
  isLast,
}: BlockRowProps) {
  const domId = `block-${index}`;
  const highlighted = useHighlighted(domId);

  return (
    <div
      id={domId}
      tabIndex={-1}
      className={`rounded-lg border p-3 transition-colors ${
        highlighted ? "border-amber-500 bg-amber-500/10" : "border-deck-700 bg-deck-800/40"
      }`}
    >
      <div className="mb-3 flex items-center justify-between">
        <span className={indexBadge}>{index + 1}</span>
        <div className="flex gap-1">
          <button
            type="button"
            aria-label={`Move ${rowLabel} ${index + 1} up`}
            disabled={isFirst}
            onClick={onMoveUp}
            className={iconButtonClass}
          >
            ↑
          </button>
          <button
            type="button"
            aria-label={`Move ${rowLabel} ${index + 1} down`}
            disabled={isLast}
            onClick={onMoveDown}
            className={iconButtonClass}
          >
            ↓
          </button>
          <button
            type="button"
            aria-label={`Remove ${rowLabel} ${index + 1}`}
            disabled={!canRemove}
            onClick={onRemove}
            className={iconButtonClass}
          >
            ×
          </button>
        </div>
      </div>
      <div className="flex flex-col gap-3">
        {Object.entries(itemSchema.properties ?? {}).map(([key, propSchema]) => (
          <SchemaField
            key={key}
            fieldKey={key}
            schema={propSchema}
            root={root}
            value={item[key]}
            onChange={(v) => onChange({ ...item, [key]: v })}
            path={[...path, key]}
            allParams={item}
            labelPrefix={labelPrefix}
          />
        ))}
      </div>
    </div>
  );
}
