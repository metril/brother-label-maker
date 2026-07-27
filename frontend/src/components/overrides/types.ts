import type { JsonSchemaObject } from "../../schema/jsonSchema";
import type { PathSegment } from "../../schema/paths";

/** Shared prop shape for every per-type/per-field override component --
 * exactly what SchemaField would have received, plus `labelType` and
 * `allParams` (sibling data no generic field ever needs, but the two
 * bespoke overrides that DO need siblings -- MultipliersField reading
 * `blocks.length`, the cable-length readouts reading `overlap_mm`/
 * `flag_length_mm` -- both do). See components/schema/overrides.ts for the
 * (labelType, fieldKey) -> component registry these implement. */
export interface OverrideFieldProps {
  fieldKey: string;
  schema: JsonSchemaObject;
  root: JsonSchemaObject;
  value: unknown;
  onChange: (value: unknown) => void;
  path: PathSegment[];
  allParams: Record<string, unknown>;
  labelType: string;
}
