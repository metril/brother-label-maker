import { resolveHelpTextOverride, resolveOverride } from "../overrides/registry";
import type { JsonSchemaObject } from "../../schema/jsonSchema";
import { SchemaField } from "./SchemaField";

interface SchemaFormProps {
  labelType: string;
  schema: JsonSchemaObject;
  params: Record<string, unknown>;
  onChange: (params: Record<string, unknown>) => void;
}

/** Top-level entry point: one `<SchemaForm>` renders a complete params form
 * for ANY of the 9 label types, straight from its own params_schema --
 * this is the "generic-first" half of task 2.10's approach (see
 * components/overrides/registry.ts for the "targeted overrides" half).
 * Overrides are resolved here (and only here -- SchemaField/ArrayOfObjects
 * never consult the registry) because every override field in this app is
 * a TOP-LEVEL field of its type's own params; nothing nested inside a
 * repeatable block/breaker row needs one today. */
export function SchemaForm({ labelType, schema, params, onChange }: SchemaFormProps) {
  const properties = schema.properties ?? {};

  return (
    <div className="flex flex-col gap-5">
      {Object.entries(properties).map(([key, propSchema]) => {
        const Override = resolveOverride(labelType, key);
        // A field with no schema-provided `description` can still get one
        // from resolveHelpTextOverride (a GAP-FILL only -- never overrides
        // a description the schema already has, see that function's own
        // docstring) by patching it in before either render path sees it.
        const helpOverride = propSchema.description === undefined ? resolveHelpTextOverride(labelType, key) : undefined;
        const patchedSchema = helpOverride ? { ...propSchema, description: helpOverride } : propSchema;
        const fieldProps = {
          fieldKey: key,
          schema: patchedSchema,
          root: schema,
          value: params[key],
          onChange: (value: unknown) => onChange({ ...params, [key]: value }),
          path: [key],
          allParams: params,
          labelType,
        };
        return <div key={key}>{Override ? <Override {...fieldProps} /> : <SchemaField {...fieldProps} />}</div>;
      })}
    </div>
  );
}
