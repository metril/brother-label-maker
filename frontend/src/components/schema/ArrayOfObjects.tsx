import { buildItemDefault } from "../../schema/defaults";
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

/** Repeatable groups -- patch_panel/faceplate's `blocks`, breaker_box's
 * `breakers`. Each row recursively renders its own item schema's
 * properties via SchemaField (so BreakerSpec's `poles` number field and
 * `lines` array-of-strings both just work, no breaker_box-specific code
 * here). Every row's DOM id is `block-{index}` regardless of the field's
 * own name -- that's the exact `object_id` divided_blocks.py's own
 * RenderWarnings use (see render/types/divided_blocks.py), so a warning
 * chip's "focus this row" click resolves correctly whether the array is
 * called `blocks` or `breakers`. */
export function ArrayOfObjects({ label, help, schema, root, value, onChange, path }: ArrayOfObjectsProps) {
  const minItems = schema.minItems ?? 0;
  const maxItems = schema.maxItems;
  const itemSchema = resolveRef(schema.items ?? {}, root);
  const atMax = maxItems !== undefined && value.length >= maxItems;

  function updateItem(i: number, next: Record<string, unknown>) {
    onChange(value.map((item, idx) => (idx === i ? next : item)));
  }
  function addItem() {
    if (atMax) return;
    onChange([...value, buildItemDefault(schema.items ?? {}, root) as Record<string, unknown>]);
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
          key={i}
          index={i}
          rowLabel={label}
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
        <span className={indexBadge}>{index}</span>
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
          />
        ))}
      </div>
    </div>
  );
}
