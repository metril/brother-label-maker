import { useState } from "react";
import type { ChainMode, LabelDefinition, PrintOptions } from "../api/types";
import { usePrintEstimate } from "../hooks/usePrintEstimate";
import { PrintButton } from "./PrintButton";
import { Checkbox } from "./ui/inputs";
import { Pending } from "./ui/Pending";
import { SegmentedControl } from "./ui/SegmentedControl";
import { eyebrow } from "./ui/styles";

const CHAIN_MODE_OPTIONS: { value: ChainMode; label: string }[] = [
  { value: "cut_each", label: "Cut each" },
  { value: "chain_ff", label: "Chain" },
  { value: "strip_marks", label: "Strip marks" },
];

interface JobTrayProps {
  definition: LabelDefinition;
  hasContent: boolean;
  isRenderable: (definition: LabelDefinition) => boolean;
}

/** The design doc's "JOB TRAY (sticky, estimate, chain mode, print)" --
 * chain mode/auto-cut choice feeds both the live tape-usage estimate
 * (POST /api/print/estimate) and the actual print request, so the number
 * shown is always the number that would actually get used. */
export function JobTray({ definition, hasContent, isRenderable }: JobTrayProps) {
  const [chainMode, setChainMode] = useState<ChainMode>("cut_each");
  const [autoCut, setAutoCut] = useState(true);
  const options: PrintOptions = { chain_mode: chainMode, margin_mm: 2.0, auto_cut: autoCut };

  const { estimate, error } = usePrintEstimate(definition, options, isRenderable);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <span className={`${eyebrow} mb-1.5 block`}>Chain mode</span>
        <SegmentedControl ariaLabel="Chain mode" value={chainMode} options={CHAIN_MODE_OPTIONS} onChange={setChainMode} />
      </div>

      <Checkbox checked={autoCut} onChange={setAutoCut} label="Auto-cut" />

      <div className="rounded-lg border border-deck-700 bg-deck-800/40 p-3">
        <p className={eyebrow}>Tape estimate</p>
        {error ? (
          <p role="alert" className="mt-1.5 text-[12px] text-rust-500">
            {error}
          </p>
        ) : !estimate ? (
          <div className="mt-1.5">
            <Pending />
          </div>
        ) : (
          <>
            <dl className="mt-2 flex flex-col gap-1 font-mono text-[13px] text-deck-200">
              <div className="flex justify-between">
                <dt className="text-deck-400">Total</dt>
                <dd>{estimate.total_mm.toFixed(1)} mm</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-deck-400">Per label</dt>
                <dd>{estimate.per_label_mm.toFixed(1)} mm</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-deck-400">Feed overhead</dt>
                <dd>{estimate.feed_overhead_mm.toFixed(1)} mm</dd>
              </div>
            </dl>
            {estimate.notes.length > 0 && (
              <ul className="mt-2 flex flex-col gap-0.5 text-[11px] leading-snug text-deck-400">
                {estimate.notes.map((note, i) => (
                  <li key={i}>· {note}</li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>

      <PrintButton definition={definition} disabled={!hasContent} options={options} />
    </div>
  );
}
