import { classifyField, resolveRef, splitNullable, type JsonSchemaObject } from "./jsonSchema";

/** Generalizes the old (text-only) hasRenderableContent: true once every
 * REQUIRED field the schema names is actually filled in, so the UI never
 * fires a preview/print request against a definition the backend is
 * guaranteed to 422 on the same way text_label.py's own `_check_lines`
 * rejects an all-blank `lines` list.
 *
 * - required STRING fields (e.g. barcode's `data`) must be non-blank after
 *   trim.
 * - required array-of-string fields (e.g. text/cable_wrap/cable_flag's
 *   `lines`) need at least one non-blank entry -- mirrors each of those
 *   types' own `_check_lines` validator exactly.
 * - required array-of-object fields (patch_panel's `blocks`, breaker_box's
 *   `breakers`) just need to be non-empty -- an object row with blank text
 *   is a perfectly valid (if blank) block, per divided_blocks.py's `lines
 *   or [""]` fallback.
 * - every other required field always has a schema `default` after
 *   buildDefaultParams seeds it, so there's nothing to gate on.
 */
export function hasRenderableContent(
  schema: JsonSchemaObject,
  params: Record<string, unknown>,
): boolean {
  const required = schema.required ?? [];
  for (const key of required) {
    const fieldSchema = schema.properties?.[key];
    if (!fieldSchema) continue;
    const { inner } = splitNullable(fieldSchema, schema);
    const resolved = resolveRef(inner, schema);
    const kind = classifyField(resolved);
    const value = params[key];

    if (kind === "string") {
      if (typeof value !== "string" || value.trim() === "") return false;
    } else if (kind === "array-string") {
      if (!Array.isArray(value) || !value.some((v) => typeof v === "string" && v.trim() !== "")) {
        return false;
      }
    } else if (kind === "array-object" || kind === "array-number") {
      if (!Array.isArray(value) || value.length === 0) return false;
    }
  }
  return true;
}
