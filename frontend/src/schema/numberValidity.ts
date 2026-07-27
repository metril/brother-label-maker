import { classifyField, resolveRef, splitNullable, type JsonSchemaObject } from "./jsonSchema";

/** True when `value` isn't a real, in-range number for `schema` -- covers
 * both "empty/cleared" (NumberInput emits `undefined` for that, see
 * components/ui/inputs.tsx) and "a real number outside minimum/maximum"
 * (e.g. typed 400 into a max-300 field). The single source of truth both
 * SchemaField's own inline per-field error AND hasNumberOutOfRange's
 * whole-definition walk below are built from, so the two can never
 * disagree about what counts as invalid. */
export function isNumberFieldInvalid(value: unknown, schema: JsonSchemaObject): boolean {
  if (typeof value !== "number" || Number.isNaN(value)) return true;
  if (schema.minimum !== undefined && value < schema.minimum) return true;
  if (schema.maximum !== undefined && value > schema.maximum) return true;
  return false;
}

/** The inline message for an invalid number field, or null when it's fine
 * -- "enter a value" for empty/cleared, the existing bounds wording
 * otherwise. */
export function numberFieldErrorMessage(value: unknown, schema: JsonSchemaObject): string | null {
  if (typeof value !== "number" || Number.isNaN(value)) return "enter a value";
  const min = schema.minimum;
  const max = schema.maximum;
  if (min !== undefined && value < min) {
    return max !== undefined ? `must be between ${min} and ${max}` : `must be at least ${min}`;
  }
  if (max !== undefined && value > max) {
    return min !== undefined ? `must be between ${min} and ${max}` : `must be at most ${max}`;
  }
  return null;
}

/** Walks a params object against its own schema -- recursing into array-of-
 * object rows (patch_panel's blocks, breaker_box's breakers) and array-of-
 * number items (patch_panel's multipliers) -- looking for any number/
 * integer field that's empty or out of its declared bounds.
 *
 * This is the client-side "is this actually safe to send" check task 2.10's
 * review found missing: SchemaField already SHOWS an inline bounds error
 * per field, but nothing stopped the preview/estimate/print request from
 * firing anyway with the very value the UI was simultaneously flagging as
 * wrong -- the backend's own pydantic 422 for the same violation was
 * winning the race every time. Designer.tsx ANDs this into the query-
 * enabling predicate (never into the loose "is there enough content to
 * attempt a render" check FeedDeck's placeholder-vs-deck branch uses --
 * clearing one incidental numeric field mid-edit shouldn't blank the whole
 * preview back to "type something", see FeedDeck.tsx).
 *
 * Nullable fields currently in Auto mode (null) are skipped -- there's
 * nothing to bound-check about "auto". Fields this generic walk can't see
 * into (the "text" type's `icon` discriminated union -- an unknown shape to
 * classifyField, see jsonSchema.ts) aren't policed here; icon's own numeric
 * sub-field (image threshold) is defensively clamped at the point of entry
 * instead (see components/overrides/IconField.tsx). */
export function hasNumberOutOfRange(
  schema: JsonSchemaObject,
  params: Record<string, unknown>,
  root: JsonSchemaObject = schema,
): boolean {
  const properties = schema.properties ?? {};
  for (const [key, propSchema] of Object.entries(properties)) {
    const { nullable, inner } = splitNullable(propSchema, root);
    const value = params[key];
    if (nullable && (value === null || value === undefined)) continue;
    const resolved = resolveRef(inner, root);
    const kind = classifyField(resolved);

    if (kind === "integer" || kind === "number") {
      if (isNumberFieldInvalid(value, resolved)) return true;
    } else if (kind === "array-number") {
      const items = Array.isArray(value) ? value : [];
      const itemSchema = resolved.items ?? {};
      if (items.some((item) => isNumberFieldInvalid(item, itemSchema))) return true;
    } else if (kind === "array-object") {
      const itemSchema = resolveRef(resolved.items ?? {}, root);
      const items = Array.isArray(value) ? (value as Record<string, unknown>[]) : [];
      if (items.some((item) => hasNumberOutOfRange(itemSchema, item, root))) return true;
    }
  }
  return false;
}
