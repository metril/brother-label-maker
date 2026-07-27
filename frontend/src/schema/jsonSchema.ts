// A small, deliberately narrow JSON Schema model -- just enough of the
// draft pydantic v2's `model_json_schema()` emits to drive a generic form
// renderer, NOT a general-purpose JSON Schema implementation. Verified
// against the 9 real label types' live params_schema output (see
// src/test/fixtures/label-types.json and scripts/gen-fixtures.mjs) rather
// than the spec in the abstract -- the shapes here are exactly the ones
// that schema actually contains.

export interface JsonSchemaObject {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: (string | number)[];
  const?: string | number;
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  minItems?: number;
  maxItems?: number;
  items?: JsonSchemaObject;
  properties?: Record<string, JsonSchemaObject>;
  required?: string[];
  anyOf?: JsonSchemaObject[];
  $ref?: string;
  $defs?: Record<string, JsonSchemaObject>;
  [key: string]: unknown;
}

/** Resolve a `$ref` (always `#/$defs/<Name>` in this codebase's output)
 * against `root`'s own `$defs` map. Non-$ref schemas pass through
 * unchanged. Only one level of indirection is ever needed for the 9 real
 * schemas (no $ref chains), but this still follows one more hop if it ever
 * finds one, rather than assuming. */
export function resolveRef(schema: JsonSchemaObject, root: JsonSchemaObject): JsonSchemaObject {
  if (!schema.$ref) return schema;
  const name = schema.$ref.replace("#/$defs/", "");
  const target = root.$defs?.[name];
  if (!target) {
    throw new Error(`unresolvable $ref ${schema.$ref} (no $defs.${name} on root schema)`);
  }
  return target.$ref ? resolveRef(target, root) : target;
}

/** pydantic's JSON Schema shape for `X | None = None`: `anyOf: [<X's own
 * schema>, {type: "null"}]` plus `default: null` on the field itself.
 * Returns the non-null branch (resolved through any $ref) when the field is
 * nullable this way, else the schema unchanged. */
export function splitNullable(
  schema: JsonSchemaObject,
  root: JsonSchemaObject,
): { nullable: boolean; inner: JsonSchemaObject } {
  if (!schema.anyOf) return { nullable: false, inner: schema };
  const nullBranch = schema.anyOf.find((branch) => branch.type === "null");
  const valueBranch = schema.anyOf.find((branch) => branch.type !== "null");
  if (!nullBranch || !valueBranch) return { nullable: false, inner: schema };
  return { nullable: true, inner: resolveRef(valueBranch, root) };
}

export type FieldKind =
  | "string"
  | "integer"
  | "number"
  | "boolean"
  | "enum"
  | "array-string"
  | "array-number"
  | "array-object"
  | "unknown";

/** Classify an already-nullable-unwrapped, already-$ref-resolved schema
 * into the one shape SchemaField knows how to render. This is the full set
 * of shapes actually present across the 9 real label types' params_schema
 * (see module docstring) -- "unknown" is a deliberate fallback for
 * anything genuinely unanticipated, rendered as a read-only note rather
 * than crashing the form. */
export function classifyField(schema: JsonSchemaObject): FieldKind {
  if (schema.enum) return "enum";
  if (schema.type === "string") return "string";
  if (schema.type === "integer") return "integer";
  if (schema.type === "number") return "number";
  if (schema.type === "boolean") return "boolean";
  if (schema.type === "array") {
    const items = schema.items ?? {};
    if (items.$ref) return "array-object";
    if (items.type === "string") return "array-string";
    if (items.type === "number" || items.type === "integer") return "array-number";
  }
  return "unknown";
}
