import { humanizeFieldName } from "../../schema/humanize";
import { numberFieldErrorMessage } from "../../schema/numberValidity";
import { NumberInput } from "../ui/inputs";
import { errorText, fieldLabelText, helpText } from "../ui/styles";
import type { OverrideFieldProps } from "./types";

function NumberFieldWithReadout({
  fieldKey,
  schema,
  value,
  onChange,
  path,
  readout,
}: OverrideFieldProps & { readout: string }) {
  const label = humanizeFieldName(fieldKey);
  const id = `field-${path.join("-")}`;
  const numValue = typeof value === "number" && !Number.isNaN(value) ? value : undefined;
  const errorMessage = numberFieldErrorMessage(value, schema);

  return (
    <div>
      <label htmlFor={id} className={`${fieldLabelText} mb-1 block`}>
        {label}
      </label>
      <NumberInput id={id} value={numValue} min={schema.minimum} max={schema.maximum} step={0.1} onChange={onChange} />
      <p className="mt-1 font-mono text-[12px] text-deck-400">{readout}</p>
      {errorMessage ? (
        <p role="alert" className={errorText}>
          {errorMessage}
        </p>
      ) : (
        schema.description && <p className={helpText}>{schema.description}</p>
      )}
    </div>
  );
}

/** cable_wrap's length is DERIVED (circumference + overlap), never
 * user-chosen -- render/types/cable_wrap.py's module docstring: `length_mm
 * = pi * cable_diameter_mm + overlap_mm`. This mirrors that formula
 * client-side as a live "≈" readout right next to the diameter field
 * itself (the feed deck's own length_mm readout says the same thing, once
 * the debounced preview lands -- this is the immediate, no-round-trip
 * version). "≈" because the real figure is snapped to the printer's device-
 * dot grid (mm_to_dots) -- the feed deck shows that exact value. */
export function CableWrapDiameterField(props: OverrideFieldProps) {
  const overlapMm = typeof props.allParams.overlap_mm === "number" ? props.allParams.overlap_mm : 5;
  const diameterMm = typeof props.value === "number" ? props.value : 0;
  const lengthMm = Math.PI * diameterMm + overlapMm;
  return <NumberFieldWithReadout {...props} readout={`≈ ${lengthMm.toFixed(1)} mm wrap length (circumference + overlap)`} />;
}

/** cable_flag's total length is likewise derived: 2 * flag_length_mm + gap,
 * where gap = pi * cable_diameter_mm + 1.0mm slack (render/types/
 * cable_flag.py's module docstring, `_GAP_SLACK_MM`). Same "≈" convention
 * as the cable_wrap readout above. */
export function CableFlagDiameterField(props: OverrideFieldProps) {
  const flagLengthMm = typeof props.allParams.flag_length_mm === "number" ? props.allParams.flag_length_mm : 20;
  const diameterMm = typeof props.value === "number" ? props.value : 0;
  const GAP_SLACK_MM = 1.0;
  const totalMm = 2 * flagLengthMm + (Math.PI * diameterMm + GAP_SLACK_MM);
  return <NumberFieldWithReadout {...props} readout={`≈ ${totalMm.toFixed(1)} mm total label length`} />;
}
