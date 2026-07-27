import type { ComponentType } from "react";
import { CableFlagDiameterField, CableWrapDiameterField } from "./CableLengthFields";
import { FontFamilyField } from "./FontFamilyField";
import { IconField } from "./IconField";
import { MultipliersField } from "./MultipliersField";
import type { OverrideFieldProps } from "./types";

/** Per the task 2.10 brief: "generic-first, with targeted overrides where a
 * bespoke control is better." Every entry here is a field the generic
 * SchemaField engine COULD render (a plain string/nullable-array), but a
 * hand-built control is genuinely more useful -- resolved by (labelType,
 * fieldKey), checked before SchemaField ever sees the field (see
 * SchemaForm.tsx). Deliberately a short, closed list, not a general escape
 * hatch -- every one of the 9 types' remaining fields still goes through
 * the generic engine untouched. */
const OVERRIDES: Record<string, ComponentType<OverrideFieldProps>> = {
  "*.font_family": FontFamilyField, // every type -- see FontFamilyField's own docstring
  "text.icon": IconField,
  "patch_panel.multipliers": MultipliersField,
  "cable_wrap.cable_diameter_mm": CableWrapDiameterField,
  "cable_flag.cable_diameter_mm": CableFlagDiameterField,
};

export function resolveOverride(labelType: string, fieldKey: string): ComponentType<OverrideFieldProps> | null {
  return OVERRIDES[`${labelType}.${fieldKey}`] ?? OVERRIDES[`*.${fieldKey}`] ?? null;
}
