import { NumberInput } from "../ui/inputs";
import { SegmentedControl } from "../ui/SegmentedControl";
import { errorText, fieldLabelText, helpText, indexBadge } from "../ui/styles";
import type { OverrideFieldProps } from "./types";

const MIN = 0.1;
const MAX = 9.5;

/** patch_panel's `multipliers`: a nullable list[float] that, when set, MUST
 * have exactly one entry per block (backend/render/types/patch_panel.py's
 * `_check_multipliers_length`) -- the one nullable ARRAY field across all 9
 * types, and the one place the generic Auto/Manual + repeatable-rows
 * machinery doesn't fit on its own (its length is derived from a sibling
 * field, `blocks`, not independently addable). Switching to Manual seeds
 * exactly `blocks.length` entries of 1.0 ("every block the same width" --
 * the same result Auto mode already produces); the row count doesn't
 * auto-follow `blocks` afterwards (edit blocks first, then multipliers) --
 * a length mismatch is called out inline here AND still 422s server-side if
 * it slips through anyway. */
export function MultipliersField({ value, onChange, allParams }: OverrideFieldProps) {
  const blocks = Array.isArray(allParams.blocks) ? allParams.blocks : [];
  const count = blocks.length;
  const isAuto = value === null || value === undefined;
  const values = Array.isArray(value) ? (value as number[]) : [];
  const mismatched = !isAuto && values.length !== count;

  function setMode(mode: "auto" | "manual") {
    if (mode === "auto") {
      onChange(null);
    } else {
      onChange(values.length === count ? values : Array.from({ length: count }, () => 1.0));
    }
  }

  function setItem(i: number, next: number) {
    onChange(values.map((v, idx) => (idx === i ? next : v)));
  }

  return (
    <div className="flex flex-col gap-2">
      <div>
        <span className={`${fieldLabelText} mb-1 block`}>Width multipliers</span>
        <SegmentedControl
          ariaLabel="Width multipliers mode"
          value={isAuto ? "auto" : "manual"}
          options={[
            { value: "auto", label: "Auto" },
            { value: "manual", label: "Manual" },
          ]}
          onChange={setMode}
        />
        {isAuto && <p className={helpText}>Every block the same width. Manual: one multiplier (0.1-9.5x) per block.</p>}
      </div>
      {!isAuto && (
        <div className="flex flex-col gap-1.5">
          {mismatched ? (
            <p role="alert" className={errorText}>
              multipliers must have exactly {count} entr{count === 1 ? "y" : "ies"} (one per block) --
              currently {values.length}
            </p>
          ) : (
            <p className={helpText}>One per block (currently {count}).</p>
          )}
          {values.map((v, i) => (
            <div key={i} className="flex items-center gap-2">
              <span className={indexBadge}>{i}</span>
              <NumberInput value={v} min={MIN} max={MAX} step={0.1} ariaLabel={`Multiplier ${i + 1}`} onChange={(next) => setItem(i, next)} />
              <span className="font-mono text-[12px] text-deck-400">x</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
