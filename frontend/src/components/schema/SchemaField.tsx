import { buildFieldDefault } from "../../schema/defaults";
import { humanizeEnumValue, humanizeFieldName } from "../../schema/humanize";
import { classifyField, resolveRef, splitNullable, type JsonSchemaObject } from "../../schema/jsonSchema";
import { numberFieldErrorMessage } from "../../schema/numberValidity";
import type { PathSegment } from "../../schema/paths";
import { Checkbox, NumberInput, Select, TextInput } from "../ui/inputs";
import { SegmentedControl } from "../ui/SegmentedControl";
import { errorText, fieldLabelText, helpText } from "../ui/styles";
import { ArrayOfNumbers } from "./ArrayOfNumbers";
import { ArrayOfObjects } from "./ArrayOfObjects";
import { ArrayOfStrings } from "./ArrayOfStrings";

export interface SchemaFieldProps {
  fieldKey: string;
  /** The raw property schema, as it appears in the parent object's
   * `properties` -- may still be $ref'd and/or nullable (anyOf w/ null);
   * resolving both is this component's own first job. */
  schema: JsonSchemaObject;
  root: JsonSchemaObject;
  value: unknown;
  onChange: (value: unknown) => void;
  path: PathSegment[];
  /** The full params object this field lives at the top level of -- lets a
   * (rare) targeted override read a sibling field, e.g. MultipliersField
   * reading `blocks.length`. Nested (array-of-object row) fields pass their
   * OWN item as allParams, which is what a nested field's siblings are. */
  allParams: Record<string, unknown>;
  /** Set only by ArrayOfObjects' BlockRow when recursing into a repeated
   * row's own fields -- "Block 2", "Breaker 1" -- so THIS field's own
   * label (and any array-of-string/array-of-object row labels nested
   * inside it) reads "Block 2 Lines 1" instead of a bare "Lines 1" that
   * collides with every other block's identical field name. Undefined at
   * the top level (no ambiguity to resolve there). */
  labelPrefix?: string;
}

/** A starting value for flipping a nullable field from Auto to Manual --
 * `buildFieldDefault` alone would pick e.g. font_size_px's schema-implied
 * default (there isn't one -- the bound itself isn't Field-visible, see
 * text_label.py's module docstring on validator-body-only bounds), so a
 * couple of fields get a hand-picked, sensible starting number instead of
 * whatever the generic zero-ish fallback would produce. */
const NULLABLE_MANUAL_SEEDS: Record<string, unknown> = {
  font_size_px: 24,
  length_mm: 40,
};

/** Recursive schema-driven field renderer -- the core of task 2.10's B: one
 * engine handles every field shape actually present across the 9 label
 * types' params_schema (string/number/bool/enum/array-of-string/array-of-
 * object/nullable-auto-manual), instead of nine hand-written forms. See
 * schema/jsonSchema.ts's module docstring for exactly which shapes that is. */
export function SchemaField({ fieldKey, schema, root, value, onChange, path, labelPrefix }: SchemaFieldProps) {
  const { nullable, inner } = splitNullable(schema, root);
  const bareLabel = humanizeFieldName(fieldKey);
  const label = labelPrefix ? `${labelPrefix} ${bareLabel}` : bareLabel;
  const help = schema.description ?? inner.description;
  const id = `field-${path.join("-")}`;

  if (nullable) {
    const isAuto = value === null || value === undefined;
    return (
      <div className="flex flex-col gap-2">
        <div>
          <span className={`${fieldLabelText} mb-1 block`}>{label}</span>
          <SegmentedControl
            ariaLabel={`${label} mode`}
            value={isAuto ? "auto" : "manual"}
            options={[
              { value: "auto", label: "Auto" },
              { value: "manual", label: "Manual" },
            ]}
            onChange={(mode) => {
              if (mode === "auto") {
                onChange(null);
              } else {
                const seed = fieldKey in NULLABLE_MANUAL_SEEDS ? NULLABLE_MANUAL_SEEDS[fieldKey] : buildFieldDefault(inner, root);
                onChange(value ?? seed);
              }
            }}
          />
          {isAuto && help && <p className={helpText}>{help}</p>}
        </div>
        {!isAuto && (
          <FieldControl
            fieldKey={fieldKey}
            schema={inner}
            root={root}
            value={value}
            onChange={onChange}
            path={path}
            id={id}
            label={label}
            help={help}
          />
        )}
      </div>
    );
  }

  return (
    <FieldControl
      fieldKey={fieldKey}
      schema={inner}
      root={root}
      value={value}
      onChange={onChange}
      path={path}
      id={id}
      label={label}
      help={help}
    />
  );
}

interface FieldControlProps {
  fieldKey: string;
  schema: JsonSchemaObject;
  root: JsonSchemaObject;
  value: unknown;
  onChange: (value: unknown) => void;
  path: PathSegment[];
  id: string;
  /** Already prefix-qualified (see SchemaFieldProps.labelPrefix) -- every
   * branch below just uses this verbatim for its visible label AND (for
   * array kinds) the repeatable-row aria-labels. */
  label: string;
  help?: string;
}

/** The actual control for an already-nullable-resolved, already-$ref-
 * resolved schema -- dispatches purely on shape (classifyField), never on
 * `fieldKey` (name-based behavior lives in overrides.ts, one layer up, not
 * here -- this component doesn't know or care what label type it's in). */
function FieldControl({ fieldKey, schema, root, value, onChange, path, id, label, help }: FieldControlProps) {
  const resolved = resolveRef(schema, root);
  const kind = classifyField(resolved);

  switch (kind) {
    case "string": {
      const strValue = typeof value === "string" ? value : "";
      return (
        <div>
          <label htmlFor={id} className={`${fieldLabelText} mb-1 block`}>
            {label}
          </label>
          <TextInput id={id} value={strValue} maxLength={resolved.maxLength} onChange={onChange} />
          {help && <p className={helpText}>{help}</p>}
        </div>
      );
    }

    case "integer":
    case "number": {
      const numValue = typeof value === "number" && !Number.isNaN(value) ? value : undefined;
      const errorMessage = numberFieldErrorMessage(value, resolved);
      return (
        <div>
          <label htmlFor={id} className={`${fieldLabelText} mb-1 block`}>
            {label}
          </label>
          <NumberInput
            id={id}
            value={numValue}
            min={resolved.minimum}
            max={resolved.maximum}
            step={kind === "integer" ? 1 : 0.1}
            onChange={(v) => onChange(v === undefined ? undefined : kind === "integer" ? Math.round(v) : v)}
          />
          {errorMessage ? (
            <p role="alert" className={errorText}>
              {errorMessage}
            </p>
          ) : (
            help && <p className={helpText}>{help}</p>
          )}
        </div>
      );
    }

    case "boolean":
      return (
        <div>
          <Checkbox id={id} checked={Boolean(value)} onChange={onChange} label={label} />
          {help && <p className={helpText}>{help}</p>}
        </div>
      );

    case "enum": {
      const enumValues = (resolved.enum ?? []).map(String);
      const strValue = typeof value === "string" ? value : (enumValues[0] ?? "");
      const options = enumValues.map((v) => ({ value: v, label: humanizeEnumValue(v) }));
      if (options.length <= 4) {
        return (
          <div>
            <span className={`${fieldLabelText} mb-1 block`}>{label}</span>
            <SegmentedControl ariaLabel={label} value={strValue} options={options} onChange={onChange} />
            {help && <p className={helpText}>{help}</p>}
          </div>
        );
      }
      return (
        <div>
          <label htmlFor={id} className={`${fieldLabelText} mb-1 block`}>
            {label}
          </label>
          <Select id={id} value={strValue} options={options} onChange={onChange} />
          {help && <p className={helpText}>{help}</p>}
        </div>
      );
    }

    case "array-string":
      return (
        <ArrayOfStrings
          label={label}
          help={help}
          schema={resolved}
          value={Array.isArray(value) ? (value as string[]) : []}
          onChange={onChange}
        />
      );

    case "array-number":
      return (
        <ArrayOfNumbers
          label={label}
          help={help}
          schema={resolved}
          value={Array.isArray(value) ? (value as number[]) : []}
          onChange={onChange}
        />
      );

    case "array-object":
      return (
        <ArrayOfObjects
          label={label}
          help={help}
          schema={resolved}
          root={root}
          value={Array.isArray(value) ? (value as Record<string, unknown>[]) : []}
          onChange={onChange}
          path={path}
        />
      );

    default:
      // Reached only for a field shape genuinely outside the 9 real
      // schemas' vocabulary (see jsonSchema.ts's module docstring) -- a
      // read-only note beats a crash for an unanticipated future field.
      return (
        <div>
          <span className={`${fieldLabelText} mb-1 block`}>{label}</span>
          <p className={helpText}>
            {fieldKey}: unsupported field shape ({JSON.stringify(resolved.type ?? resolved)})
          </p>
        </div>
      );
  }
}
