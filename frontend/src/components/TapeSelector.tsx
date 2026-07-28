import type { Tape, TapeFamily } from "../api/types";
import { useTapes } from "../hooks/useTapes";
import { Pending } from "./ui/Pending";
import { SegmentedControl } from "./ui/SegmentedControl";
import { errorText, eyebrow, segmentedButtonClass } from "./ui/styles";

const FAMILY_ORDER: TapeFamily[] = ["tze", "hse_2_1", "hse_3_1"];
const FAMILY_LABELS: Record<TapeFamily, string> = {
  tze: "TZe",
  hse_2_1: "HSe 2:1",
  hse_3_1: "HSe 3:1",
};

interface TapeSelectorProps {
  tape: Tape;
  onChange: (tape: Tape) => void;
}

/** Tape family + width picker, driven entirely by GET /api/tapes
 * (backend/driver/geometry.py's all_tapes() -- TZe + both HSe heat-shrink
 * families) -- "widths from /api/tapes filtered by family" per the task
 * brief. Switching family snaps the width to that family's own smallest
 * tape (the old width almost never exists in the new family's catalog). */
export function TapeSelector({ tape, onChange }: TapeSelectorProps) {
  const { data: tapes, isPending, isError, refetch, isRefetching } = useTapes();

  // Task 4.3 fix-up: a failed GET /api/tapes used to leave this stuck on
  // the placeholder branch below forever. react-query's `isPending` DOES
  // flip false once retries exhaust (status becomes "error") -- but `data`
  // stays undefined, so the old `isPending || !tapes` guard kept rendering
  // the quiet `···` with no error text and no way to try again short of a
  // full reload. `isError` is checked FIRST and independently so the
  // failure always shows once it has actually happened; the `!tapes` half
  // of the guard below is still load-bearing for the pending case.
  if (isError) {
    return (
      <div className="flex flex-col gap-2">
        <span className={eyebrow}>Tape</span>
        <p role="alert" className={errorText}>
          Could not load tape types.{" "}
          <button type="button" onClick={() => void refetch()} disabled={isRefetching} className="font-medium text-amber-300 hover:underline disabled:opacity-60">
            {isRefetching ? "Retrying…" : "Retry"}
          </button>
        </p>
      </div>
    );
  }

  if (isPending || !tapes) {
    return (
      <div className="flex flex-col gap-2">
        <span className={eyebrow}>Tape</span>
        <Pending />
      </div>
    );
  }

  const families = FAMILY_ORDER.filter((family) => tapes.some((t) => t.family === family));
  const widths = tapes.filter((t) => t.family === tape.family).sort((a, b) => a.nominal_mm - b.nominal_mm);

  function setFamily(family: TapeFamily) {
    const firstWidth = tapes!.filter((t) => t.family === family).sort((a, b) => a.nominal_mm - b.nominal_mm)[0];
    onChange({ width_mm: firstWidth?.nominal_mm ?? tape.width_mm, family });
  }

  return (
    <div className="flex flex-col gap-2">
      <span className={eyebrow}>Tape</span>
      <SegmentedControl
        ariaLabel="Tape family"
        value={tape.family}
        options={families.map((f) => ({ value: f, label: FAMILY_LABELS[f] }))}
        onChange={setFamily}
      />
      <div role="group" aria-label="Tape width" className="flex flex-wrap gap-2">
        {widths.map((t) => {
          const selected = t.nominal_mm === tape.width_mm;
          return (
            <button
              key={t.nominal_mm}
              type="button"
              aria-pressed={selected}
              onClick={() => onChange({ ...tape, width_mm: t.nominal_mm })}
              className={`${segmentedButtonClass(selected)} font-mono`}
            >
              {t.nominal_mm}mm
            </button>
          );
        })}
      </div>
    </div>
  );
}
