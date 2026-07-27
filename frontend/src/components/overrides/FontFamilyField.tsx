import { useFonts } from "../../hooks/useFonts";
import { humanizeFieldName } from "../../schema/humanize";
import { Pending } from "../ui/Pending";
import { Select } from "../ui/inputs";
import { fieldLabelText, helpText } from "../ui/styles";
import type { OverrideFieldProps } from "./types";

/** Every label type's `font_family` field (a bare `type: string` in the
 * schema -- pydantic doesn't know the valid set, it's a runtime
 * `_VALID_FAMILIES` check) gets the real bundled catalog from GET
 * /api/fonts instead of a free-text box a typo could 422. Field-name-keyed
 * (see overrides.ts), not type-keyed -- it's the same override across all
 * 9 types. */
export function FontFamilyField({ fieldKey, value, onChange, path }: OverrideFieldProps) {
  const { data: fonts, isPending } = useFonts();
  const label = humanizeFieldName(fieldKey);
  const id = `field-${path.join("-")}`;
  const strValue = typeof value === "string" ? value : "Inter";

  return (
    <div>
      <label htmlFor={id} className={`${fieldLabelText} mb-1 block`}>
        {label}
      </label>
      {isPending || !fonts ? (
        <Pending />
      ) : (
        <Select
          id={id}
          value={strValue}
          onChange={onChange}
          options={fonts.map((font) => ({ value: font.family, label: font.display_name }))}
        />
      )}
      <p className={helpText}>Bundled font family (see GET /api/fonts).</p>
    </div>
  );
}
