import { useState } from "react";
import { useSequenceExpand } from "../hooks/useSequenceExpand";
import { collationPattern, DEFAULT_SEQUENCE, parseListTextarea, SEQUENCE_KIND_OPTIONS } from "../lib/sequence";
import { useDesignerStore } from "../stores/designer";
import { SequenceCsvUpload } from "./SequenceCsvUpload";
import { Checkbox, NumberInput, Textarea, TextInput } from "./ui/inputs";
import { Pending } from "./ui/Pending";
import { SegmentedControl } from "./ui/SegmentedControl";
import { errorText, eyebrow, fieldLabelText, helpText } from "./ui/styles";
import type { Collation, ExpandResponse, Sequence, SequenceKind } from "../api/types";
import type { SequenceFieldErrors } from "../lib/sequence";

/** task 2.11: the collapsible "Serialize" panel -- off by default (a
 * single toggle turns it on), turning one label design into a print RUN
 * (numbered/lettered/list/CSV-driven) instead of a single label. Fully
 * self-contained: reads/writes serialization state straight from the
 * designer store rather than taking props, so mounting it here is the
 * ENTIRE integration cost for pages/Designer.tsx (which additionally
 * reads the same store fields + useSequenceExpand() itself to wire the
 * feed deck's preview-index stepper and the Job Tray's request body --
 * see that file). Placed as its own full-width panel BELOW the
 * parameters-form/job-tray row (not inside either column): it applies
 * across both of them (drives the feed deck's stepper above AND the
 * Job Tray/Print button below), so a shared panel there reads clearer
 * than nesting it in one column -- brief's own "your call, document it". */
export function SequenceEditor() {
  const enabled = useDesignerStore((s) => s.serializationEnabled);
  const setEnabled = useDesignerStore((s) => s.setSerializationEnabled);
  const sequence = useDesignerStore((s) => s.sequence);
  const setSequence = useDesignerStore((s) => s.setSequence);
  const expand = useSequenceExpand();

  function patch(partial: Partial<Sequence>) {
    setSequence({ ...sequence, ...partial });
  }

  function switchKind(kind: SequenceKind) {
    // Universal fields (copies/collation) survive a kind switch; every
    // kind-specific field resets to its default rather than carrying over
    // a stale numeric/alpha/list/csv value that no longer applies.
    setSequence({
      ...DEFAULT_SEQUENCE,
      kind,
      copies_per_value: sequence.copies_per_value,
      collation: sequence.collation,
    });
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center justify-between gap-4">
        <span className={eyebrow}>Serialize</span>
        <Checkbox id="serialize-toggle" checked={enabled} onChange={setEnabled} label="On" />
      </div>

      {!enabled ? (
        <p className="text-[13px] text-deck-400">
          Turn on to print a numbered, lettered, list, or CSV-driven run instead of one label.
        </p>
      ) : (
        <>
          <div>
            <span className={`${fieldLabelText} mb-1.5 block`}>Kind</span>
            <SegmentedControl ariaLabel="Serialization kind" value={sequence.kind} options={SEQUENCE_KIND_OPTIONS} onChange={switchKind} />
          </div>

          {sequence.kind === "numeric" && <NumericFields sequence={sequence} errors={expand.fieldErrors} onPatch={patch} />}
          {sequence.kind === "alpha" && <AlphaFields sequence={sequence} errors={expand.fieldErrors} onPatch={patch} />}
          {sequence.kind === "list" && <ListValuesField values={sequence.values ?? []} error={expand.fieldErrors.values} onChange={(values) => patch({ values })} />}
          {sequence.kind === "csv" && <SequenceCsvUpload sequence={sequence} onPatch={patch} />}
          {expand.fieldErrors.rows && sequence.kind === "csv" && (
            <p role="alert" className={errorText}>
              {expand.fieldErrors.rows}
            </p>
          )}

          <CopiesCollation sequence={sequence} errors={expand.fieldErrors} onPatch={patch} demoValues={expand.data?.values ?? []} />

          <LiveChips
            data={expand.data}
            error={expand.error}
            isFetching={expand.isFetching}
            sampleHasToken={expand.sampleHasToken}
          />
        </>
      )}
    </div>
  );
}

function NumericFields({ sequence, errors, onPatch }: { sequence: Sequence; errors: SequenceFieldErrors; onPatch: (p: Partial<Sequence>) => void }) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <SequenceNumberField
        id="sequence-start"
        label="Start"
        value={sequence.start}
        error={errors.start}
        min={-999999}
        max={999999}
        onChange={(v) => onPatch({ start: v })}
      />
      <SequenceNumberField
        id="sequence-step"
        label="Step"
        value={sequence.step}
        error={errors.step}
        min={-9999}
        max={9999}
        onChange={(v) => onPatch({ step: v })}
      />
      <SequenceNumberField
        id="sequence-count"
        label="Count"
        value={sequence.count}
        error={errors.count}
        min={1}
        max={500}
        onChange={(v) => onPatch({ count: v })}
      />
      <SequenceNumberField
        id="sequence-pad-width"
        label="Zero-pad width"
        value={sequence.pad_width}
        error={errors.padWidth}
        min={0}
        max={6}
        onChange={(v) => onPatch({ pad_width: v })}
      />
    </div>
  );
}

function AlphaFields({ sequence, errors, onPatch }: { sequence: Sequence; errors: SequenceFieldErrors; onPatch: (p: Partial<Sequence>) => void }) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <div>
        <label htmlFor="sequence-alpha-start" className={`${fieldLabelText} mb-1 block`}>
          Start letter(s)
        </label>
        <TextInput
          id="sequence-alpha-start"
          value={sequence.alpha_start ?? "A"}
          maxLength={3}
          onChange={(v) => onPatch({ alpha_start: v.toUpperCase() })}
          className="w-full rounded-md border border-deck-600 bg-deck-800 px-3 py-1.5 font-mono text-[14px] text-deck-200"
        />
        {errors.alphaStart && (
          <p role="alert" className={errorText}>
            {errors.alphaStart}
          </p>
        )}
      </div>
      <SequenceNumberField
        id="sequence-alpha-step"
        label="Step"
        value={sequence.step}
        error={errors.step}
        min={-9999}
        max={9999}
        onChange={(v) => onPatch({ step: v })}
      />
      <SequenceNumberField
        id="sequence-alpha-count"
        label="Count"
        value={sequence.count}
        error={errors.count}
        min={1}
        max={500}
        onChange={(v) => onPatch({ count: v })}
      />
    </div>
  );
}

interface SequenceNumberFieldProps {
  id: string;
  label: string;
  value: number | undefined;
  error?: string;
  min?: number;
  max?: number;
  onChange: (value: number | undefined) => void;
}

function SequenceNumberField({ id, label, value, error, min, max, onChange }: SequenceNumberFieldProps) {
  return (
    <div>
      <label htmlFor={id} className={`${fieldLabelText} mb-1 block`}>
        {label}
      </label>
      <NumberInput id={id} value={value} min={min} max={max} step={1} onChange={onChange} />
      {error && (
        <p role="alert" className={errorText}>
          {error}
        </p>
      )}
    </div>
  );
}

function ListValuesField({ values, error, onChange }: { values: string[]; error?: string; onChange: (values: string[]) => void }) {
  // A local, uncontrolled-by-`values` text buffer -- see lib/sequence.ts's
  // parseListTextarea docstring for why: re-deriving the textarea's own
  // displayed text from the PARSED `values` array on every render would
  // strip a blank line the instant the user types it (before they've had
  // a chance to type the next value on it), fighting the user mid-edit
  // the same way a naive NumberInput would (see ui/inputs.tsx's own `raw`
  // buffer for the established precedent).
  const [raw, setRaw] = useState(() => values.join("\n"));

  return (
    <div>
      <label htmlFor="sequence-list-values" className={`${fieldLabelText} mb-1 block`}>
        Values (one per line)
      </label>
      <Textarea
        id="sequence-list-values"
        value={raw}
        rows={6}
        onChange={(next) => {
          setRaw(next);
          onChange(parseListTextarea(next));
        }}
      />
      <p className={helpText}>
        {values.length} value{values.length === 1 ? "" : "s"}.
      </p>
      {error && (
        <p role="alert" className={errorText}>
          {error}
        </p>
      )}
    </div>
  );
}

function CopiesCollation({
  sequence,
  errors,
  onPatch,
  demoValues,
}: {
  sequence: Sequence;
  errors: SequenceFieldErrors;
  onPatch: (p: Partial<Sequence>) => void;
  demoValues: string[];
}) {
  const collation: Collation = sequence.collation ?? "copies_adjacent";
  const { pattern, more } = collationPattern(demoValues, sequence.copies_per_value ?? 1, collation);

  return (
    <div className="flex flex-col gap-3 border-t border-deck-800 pt-4">
      <SequenceNumberField
        id="sequence-copies"
        label="Copies per value"
        value={sequence.copies_per_value}
        error={errors.copiesPerValue}
        min={1}
        max={100}
        onChange={(v) => onPatch({ copies_per_value: v })}
      />

      <div>
        <span className={`${fieldLabelText} mb-1 block`}>Collation</span>
        <SegmentedControl
          ariaLabel="Collation"
          value={collation}
          options={[
            { value: "copies_adjacent", label: "Copies adjacent" },
            { value: "sequence_repeated", label: "Sequence repeated" },
          ]}
          onChange={(v) => onPatch({ collation: v })}
        />
        <p className={helpText}>
          {collation === "sequence_repeated"
            ? "The whole run repeats, in order: A B A B."
            : "Every copy of a value sits together: A A B B."}
        </p>
      </div>

      {pattern.length > 0 && (
        <div className="flex flex-wrap items-center gap-1">
          {pattern.map((v, i) => (
            <span key={i} className="rounded border border-deck-600 bg-deck-800 px-1.5 py-0.5 font-mono text-[11px] text-deck-200">
              {v}
            </span>
          ))}
          {more > 0 && <span className="text-[11px] text-deck-400">… and {more} more</span>}
        </div>
      )}
    </div>
  );
}

function LiveChips({
  data,
  error,
  isFetching,
  sampleHasToken,
}: {
  data: ExpandResponse | null;
  error: string | null;
  isFetching: boolean;
  sampleHasToken: boolean;
}) {
  const chips = sampleHasToken && data?.samples ? data.samples : (data?.values ?? []);
  const shown = chips.slice(0, 24);
  const more = chips.length - shown.length;

  return (
    <div className="rounded-lg border border-deck-700 bg-deck-800/40 p-3">
      <div className="mb-2 flex items-center justify-between gap-3">
        <span className={eyebrow}>Preview</span>
        {data && (
          <span className="font-mono text-[16px] leading-none text-deck-200">
            {data.total_labels} label{data.total_labels === 1 ? "" : "s"}
          </span>
        )}
      </div>
      {error ? (
        <p role="alert" className={errorText}>
          {error}
        </p>
      ) : !data ? (
        <div className="flex items-center gap-2">
          <Pending />
          {isFetching && <span className="text-[12px] text-deck-400">resolving…</span>}
        </div>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {shown.map((v, i) => (
            <span key={i} className="rounded-full border border-deck-600 bg-deck-800 px-2 py-0.5 font-mono text-[11px] text-deck-200">
              {v}
            </span>
          ))}
          {more > 0 && <span className="px-1 py-0.5 text-[11px] text-deck-400">… and {more} more</span>}
        </div>
      )}
    </div>
  );
}
