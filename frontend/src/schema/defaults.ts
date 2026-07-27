import { classifyField, resolveRef, splitNullable, type JsonSchemaObject } from "./jsonSchema";

/** A sensible starting value for a bounded number with no schema `default`
 * (only ever reached for array ITEM schemas -- every top-level field in the
 * 9 real types carries its own explicit `default`, see buildDefaultParams).
 * Prefers 1 when it's in range (matches e.g. a fresh width_multiplier of
 * 1.0 -- "every block the same width"), else clamps to whichever bound
 * exists. */
function sensibleNumberDefault(schema: JsonSchemaObject): number {
  const min = schema.minimum;
  const max = schema.maximum;
  if ((min === undefined || min <= 1) && (max === undefined || max >= 1)) return 1;
  if (min !== undefined) return min;
  if (max !== undefined) return max;
  return 0;
}

/** Build a single field's default value strictly from what its own schema
 * says -- an explicit `default` wins outright (that's the backend's own
 * default, always trusted verbatim); otherwise a type-appropriate empty/
 * zero value, recursing into arrays/objects. Nullable fields with no
 * explicit default fall back to `null` (auto mode) -- see splitNullable. */
export function buildFieldDefault(schema: JsonSchemaObject, root: JsonSchemaObject): unknown {
  if ("default" in schema) return schema.default;

  const { nullable, inner } = splitNullable(schema, root);
  if (nullable) return null;

  const resolved = resolveRef(inner, root);
  const kind = classifyField(resolved);

  switch (kind) {
    case "string":
      return "";
    case "integer":
    case "number":
      return sensibleNumberDefault(resolved);
    case "boolean":
      return false;
    case "enum":
      return resolved.enum?.[0] ?? "";
    case "array-string":
    case "array-number":
    case "array-object": {
      const minItems = resolved.minItems ?? 0;
      const itemSchema = resolved.items ?? {};
      return Array.from({ length: minItems }, () => buildFieldDefault(itemSchema, root));
    }
    default:
      if (resolved.properties) return buildDefaultParams(resolved, root);
      return null;
  }
}

/** Build a full params object's defaults straight from its own JSON Schema
 * -- every one of the 9 label types' initial form state comes from this,
 * not a hand-written per-type default object (see task 2.10 brief: generic-
 * first, targeted overrides only where a bespoke control earns one). */
export function buildDefaultParams(
  schema: JsonSchemaObject,
  root: JsonSchemaObject = schema,
): Record<string, unknown> {
  const props = schema.properties ?? {};
  const out: Record<string, unknown> = {};
  for (const [key, propSchema] of Object.entries(props)) {
    out[key] = buildFieldDefault(propSchema, root);
  }
  return out;
}

/** Build one new row's default value for an array-of-object/array-of-string
 * field -- used by "+ Add" buttons (NOT the initial buildDefaultParams
 * seeding, which only ever creates `minItems` rows). Same field-shape
 * logic as buildFieldDefault's array branch, just for a single item. */
export function buildItemDefault(itemSchema: JsonSchemaObject, root: JsonSchemaObject): unknown {
  return buildFieldDefault(itemSchema, root);
}
