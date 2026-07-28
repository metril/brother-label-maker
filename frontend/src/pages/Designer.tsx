import { useEffect, useRef, useState } from "react";
import { HighlightContext } from "../components/schema/HighlightContext";
import { SchemaForm } from "../components/schema/SchemaForm";
import { FeedDeck } from "../components/FeedDeck";
import { JobTray, type CurrentDesign } from "../components/JobTray";
import { SavePresetDialog } from "../components/SavePresetDialog";
import { SequenceEditor } from "../components/SequenceEditor";
import { TapeSelector } from "../components/TapeSelector";
import { Pending } from "../components/ui/Pending";
import { panel, panelHeading, typeHeading } from "../components/ui/styles";
import { usePreview } from "../hooks/usePreview";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import { useLabelTypes } from "../hooks/useLabelTypes";
import { usePrinterStatus } from "../hooks/usePrinterStatus";
import { useSequenceExpand } from "../hooks/useSequenceExpand";
import { useTapes } from "../hooks/useTapes";
import { describeCurrentDesign } from "../lib/tray";
import { hasSequenceFieldError, sequenceTotalLabels } from "../lib/sequence";
import { hasNumberOutOfRange } from "../schema/numberValidity";
import { hasRenderableContent } from "../schema/renderable";
import { buildDefinition, tapeMismatchWarning, useDesignerStore } from "../stores/designer";
import { useTrayStore } from "../stores/tray";
import type { LabelDefinition } from "../api/types";

const HIGHLIGHT_MS = 2000;

/** The designer page: per the design doc's layout, a full-width feed deck
 * (the hero) on top, then a parametric form (left, scrolls) beside a
 * sticky job tray (right) below it. The left TYPES rail lives one level up
 * in AppShell, not here -- this page only reacts to whichever type it
 * says is selected. */
export function Designer() {
  const { data: labelTypes } = useLabelTypes();
  const { data: tapes } = useTapes();
  const tape = useDesignerStore((s) => s.tape);
  const selectedType = useDesignerStore((s) => s.selectedType);
  const paramsByType = useDesignerStore((s) => s.paramsByType);
  const setTapeWidthMm = useDesignerStore((s) => s.setTapeWidthMm);
  const setTapeFamily = useDesignerStore((s) => s.setTapeFamily);
  const setParams = useDesignerStore((s) => s.setParams);
  const serializationEnabled = useDesignerStore((s) => s.serializationEnabled);
  const sequence = useDesignerStore((s) => s.sequence);
  const addTrayItem = useTrayStore((s) => s.addItem);

  const [highlightId, setHighlightId] = useState<string | null>(null);
  const highlightTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reducedMotion = usePrefersReducedMotion();

  // task 2.11: the feed deck's own preview-index stepper -- which of the
  // serialized run's expanded labels the deck currently renders. UI-only
  // state (not designer-store: nothing outside this page reads it), reset
  // to 0 whenever serialization is off, and re-clamped whenever the
  // confirmed total label count shrinks below the current index (kind
  // switch, a shorter list, copies_per_value turned down, ...).
  const [previewIndex, setPreviewIndex] = useState(0);
  const sequenceExpand = useSequenceExpand();
  // Review fix-up (I2, same class as useSequenceExpand.ts's own fix): the
  // GATE and the VALUE sent must come from the SAME snapshot of `sequence`.
  // The original version gated on `sequenceExpand.data` (the last
  // CONFIRMED, debounced result -- can lag the live `sequence` by up to
  // useSequenceExpand's own 300ms) while sending the LIVE `sequence` --
  // editing a confirmed-valid run into an invalid one (e.g. clearing
  // `count`, or pushing it out of bounds) kept `activeSerialization` == the
  // now-invalid live sequence for one cycle, because the STALE confirmed
  // data hadn't cleared yet. Confirmed live (chrome-devtools): real 422s on
  // /api/print/estimate AND /api/render/preview, with the deck flashing a
  // raw validation-error dump before self-correcting.
  //
  // Fixed the same way canSubmit already gates the params form: a
  // SYNCHRONOUS, always-fresh check of the CURRENT `sequence`
  // (validateSequence's own per-field bounds, lib/sequence.ts) -- no
  // dependency on any debounced/stale signal at all, so gate and value can
  // never disagree. usePreview/usePrintEstimate's OWN internal debounce
  // then naturally "smooths over" every edit exactly as it already does
  // for the template: any request they actually fire carries either the
  // LAST known-good `activeSerialization` or the freshly-nulled one, never
  // a live invalid one caught mid-edit.
  //
  // This does NOT replicate the cross-field total-labels cap (by design --
  // see useSequenceExpand.ts) -- a SETTLED over-cap sequence still reaches
  // usePreview/usePrintEstimate once, and still 422s there, same as any
  // other server-only cross-field rule in this app (e.g. breaker_box's
  // numbering-scheme parity check) -- but that's now a single, STABLE,
  // correctly-worded error, not a stale one-cycle flash.
  const activeSerialization = serializationEnabled && !hasSequenceFieldError(sequence) ? sequence : null;
  const sequenceTotal = sequenceExpand.data?.total_labels ?? null;
  // Print must stay disabled through that same over-cap window (the
  // brief's own "over-cap blocks print" requirement) -- gating Print on
  // `activeSerialization` ALONE wouldn't cover it (per-field checks don't
  // see the total cap). Requiring the CONFIRMED result to also match the
  // live sequence's own (uncapped) arithmetic total closes the remaining
  // staleness gap for Print specifically: a stale confirmed total left
  // over from BEFORE an edit that changed count/copies (the over-cap
  // scenario's own shape) never coincidentally matches the new live total,
  // so Print stays disabled until a FRESH confirmation actually agrees
  // with what's on screen right now.
  const confirmedMatchesLive = sequenceExpand.data !== null && sequenceExpand.data.total_labels === sequenceTotalLabels(sequence);

  useEffect(() => {
    if (!serializationEnabled) {
      setPreviewIndex(0);
      return;
    }
    if (sequenceTotal !== null && previewIndex > sequenceTotal - 1) {
      setPreviewIndex(Math.max(0, sequenceTotal - 1));
    }
  }, [serializationEnabled, sequenceTotal, previewIndex]);

  useEffect(() => {
    return () => {
      if (highlightTimerRef.current) clearTimeout(highlightTimerRef.current);
    };
  }, []);

  const selectType = useDesignerStore((s) => s.selectType);
  // Bootstrap: select the first type once the catalog loads, if nothing's
  // selected yet (first visit / a full reload). Owned here (not TypeRail)
  // so this page works whether or not the rail happens to be mounted
  // alongside it (e.g. under test).
  useEffect(() => {
    if (selectedType == null && labelTypes && labelTypes.length > 0) {
      selectType(labelTypes[0]!.type, labelTypes[0]!.params_schema);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedType, labelTypes]);

  const typeInfo = labelTypes?.find((t) => t.type === selectedType) ?? null;
  const params = (selectedType && paramsByType[selectedType]) || {};
  // A fallback empty schema keeps every hook below callable on the very
  // first render too, before GET /api/label-types resolves -- the "still
  // loading" return happens AFTER every hook call in this component, never
  // before (Rules of Hooks: same hooks, same order, every render).
  const schema = typeInfo?.params_schema ?? { type: "object", properties: {} };
  const definition = buildDefinition(selectedType ?? "text", tape, params);

  // Two DELIBERATELY different gates, not one:
  //
  // `hasContent` (loose) -- FeedDeck's ONLY signal for placeholder-vs-deck
  // ("Type something to preview your label." vs the real strip) AND for
  // whether its derived readouts (length, warning chips) may show at all.
  // Required-content only (schema/renderable.ts) -- deliberately blind to
  // whether some OTHER, non-required numeric field happens to be out of
  // range right now, so clearing e.g. padding_mm mid-edit doesn't blank the
  // whole deck back to the empty state while there's still real "PORT 1"
  // text content sitting right there.
  //
  // `canSubmit` (strict) -- gates the actual network requests
  // (usePreview/usePrintEstimate's `enabled`) AND the Print button: ANDs in
  // hasNumberOutOfRange too, so a field the UI is ALREADY showing an inline
  // bounds/empty error for never also gets sent in a request the backend
  // was always going to 422 on. When canSubmit goes false but hasContent
  // stays true (the out-of-range case), the query is simply disabled --
  // react-query's placeholderData then keeps showing the LAST successful
  // preview/estimate (see usePreview.ts), which is exactly "keep the last
  // good preview and show the inline error" from the field itself.
  const hasContent = typeInfo !== null && hasRenderableContent(schema, params);
  const canSubmit = (def: LabelDefinition) =>
    typeInfo !== null && hasRenderableContent(schema, def.params) && !hasNumberOutOfRange(schema, def.params);

  const preview = usePreview(definition, canSubmit, activeSerialization, activeSerialization ? previewIndex : 0);
  const tapeInfo = tapes?.find((t) => t.family === tape.family && t.nominal_mm === tape.width_mm) ?? null;

  // The template itself must still be renderable (canSubmit(definition)),
  // AND -- only when serialization is on -- the live sequence must be
  // field-valid AND its total must match a FRESH server confirmation
  // (confirmedMatchesLive, see above). This is what disables Print for the
  // over-cap case (total > 1000 -- the expand request 422s, so
  // sequenceExpand.data stays null) without duplicating that cross-field
  // check client-side, and without the stale-confirmation gap
  // `activeSerialization` alone would leave open right after an edit; see
  // useSequenceExpand.ts's own docstring.
  const jobTrayCanSubmit = canSubmit(definition) && (!serializationEnabled || (activeSerialization !== null && confirmedMatchesLive));

  const printerStatus = usePrinterStatus();
  const tapeWarning = tapeMismatchWarning(
    tape.width_mm,
    printerStatus.data?.connected ?? false,
    printerStatus.data?.status?.media_width_mm,
  );

  function handleFocusObject(objectId: string) {
    setHighlightId(objectId);
    const el = document.getElementById(objectId);
    el?.focus();
    // scrollIntoView isn't implemented in every test/legacy environment --
    // guarded so a missing polyfill there can't turn a warning-chip click
    // into a hard crash.
    el?.scrollIntoView?.({ behavior: reducedMotion ? "auto" : "smooth", block: "center" });
    if (highlightTimerRef.current) clearTimeout(highlightTimerRef.current);
    highlightTimerRef.current = setTimeout(() => setHighlightId(null), HIGHLIGHT_MS);
  }

  if (!selectedType || !typeInfo) {
    return (
      <div className={panel}>
        <Pending />
      </div>
    );
  }

  // task 2.12: the "current, unsaved design" half of what the Job tray can
  // print (see components/JobTray.tsx's own CurrentDesign doc) -- built
  // here since this page owns the schema/params/preview it's derived from.
  const currentDesign: CurrentDesign = {
    definition,
    canSubmit: jobTrayCanSubmit,
    isRenderable: canSubmit,
    png: preview.png,
    lengthMm: preview.lengthMm,
    label: describeCurrentDesign(typeInfo.title, schema, params),
    serializationEnabled,
    serialization: activeSerialization,
    totalLabels: sequenceTotal,
    serializationHasVisibleError: sequenceExpand.error !== null,
  };

  function handleAddToTray() {
    if (!currentDesign.canSubmit) return;
    addTrayItem({
      definition: structuredClone(currentDesign.definition),
      png: currentDesign.png,
      lengthMm: currentDesign.lengthMm,
      label: currentDesign.label,
    });
  }

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 pb-24 lg:pb-0">
      <section className={panel}>
        <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
          <h2 className={typeHeading}>{typeInfo.title}</h2>
          <TapeSelector
            tape={tape}
            onChange={(next) => {
              if (next.family !== tape.family) setTapeFamily(next.family);
              if (next.width_mm !== tape.width_mm) setTapeWidthMm(next.width_mm);
            }}
          />
        </div>
        {/* The ONE place this warning shows -- see JobTray/Designer's own
            history for why a second copy next to Print was removed: the
            role="alert" here is announced immediately regardless, and the
            Job tray (task 2.12: a sticky sidebar at lg:, a fixed bottom
            bar/sheet below that) is reachable from every viewport without
            needing a second copy. */}
        {tapeWarning && (
          <div role="alert" className="mb-4 rounded-md border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-[13px] text-amber-300">
            {tapeWarning}
          </div>
        )}
        <FeedDeck
          tape={tape}
          tapeInfo={tapeInfo}
          hasContent={hasContent}
          png={preview.png}
          lengthMm={preview.lengthMm}
          minFeedMm={preview.minFeedMm}
          warnings={preview.warnings}
          isFetching={preview.isFetching}
          error={preview.error}
          onFocusObject={handleFocusObject}
          sequenceStepper={
            activeSerialization && sequenceTotal
              ? {
                  index: previewIndex,
                  total: sequenceTotal,
                  sequenceValue: preview.sequenceValue,
                  onIndexChange: setPreviewIndex,
                }
              : null
          }
        />
      </section>

      <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
        {/* JobTray (task 2.12) owns its OWN full responsive shell now --
            a sticky sidebar here at lg: and above, and a `position: fixed`
            bottom bar/sheet below that (out of normal document flow, so it
            no longer needs the old mobile reorder trick to keep the form
            reachable without scrolling past it -- see that component's own
            docstring). */}
        <section className={`${panel} min-w-0 flex-1`}>
          <h2 className={panelHeading}>Parameters</h2>
          <HighlightContext.Provider value={highlightId}>
            <SchemaForm
              labelType={selectedType}
              schema={schema}
              params={params}
              onChange={(next) => setParams(selectedType, next)}
            />
          </HighlightContext.Provider>
        </section>

        <JobTray current={currentDesign} onAddToTray={handleAddToTray} />
      </div>

      {/* task 2.13: "Save current design as preset", placed directly below
          the tray it saves a snapshot of (the brief's own "near the tray")
          -- full-width so it reads clearly on every viewport rather than
          only living inside the desktop sidebar column. */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-deck-800 bg-deck-900/40 px-4 py-3">
        <p className="text-[13px] text-deck-400">Like this design? Save it to reuse later without rebuilding it.</p>
        <SavePresetDialog
          labelType={selectedType}
          labelTypeTitle={typeInfo.title}
          params={params}
          tape={tape}
          disabled={!currentDesign.canSubmit}
        />
      </div>

      {/* task 2.11: a third, full-width panel BELOW the parameters-form/
          job-tray row -- see components/SequenceEditor.tsx's own docstring
          for why here rather than nested in either column above. */}
      <section className={panel}>
        <SequenceEditor />
      </section>
    </div>
  );
}
