import { useEffect, useRef, useState } from "react";
import { HighlightContext } from "../components/schema/HighlightContext";
import { SchemaForm } from "../components/schema/SchemaForm";
import { FeedDeck } from "../components/FeedDeck";
import { JobTray } from "../components/JobTray";
import { TapeSelector } from "../components/TapeSelector";
import { Pending } from "../components/ui/Pending";
import { panel, panelHeading, typeHeading } from "../components/ui/styles";
import { usePreview } from "../hooks/usePreview";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import { useLabelTypes } from "../hooks/useLabelTypes";
import { usePrinterStatus } from "../hooks/usePrinterStatus";
import { useTapes } from "../hooks/useTapes";
import { hasNumberOutOfRange } from "../schema/numberValidity";
import { hasRenderableContent } from "../schema/renderable";
import { buildDefinition, tapeMismatchWarning, useDesignerStore } from "../stores/designer";
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

  const [highlightId, setHighlightId] = useState<string | null>(null);
  const highlightTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reducedMotion = usePrefersReducedMotion();

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

  const preview = usePreview(definition, canSubmit);
  const tapeInfo = tapes?.find((t) => t.family === tape.family && t.nominal_mm === tape.width_mm) ?? null;

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

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
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
            Job panel sits right below this on every viewport (the mobile
            reorder below puts it directly under the deck). */}
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
        />
      </section>

      <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
        {/* Mobile: the Job tray (chain mode, estimate, Print) comes right
            after the feed deck, before the parametric form -- so the
            primary action is reachable without scrolling past a
            potentially long form first. Desktop: back to the design doc's
            own left-form/right-tray order via lg:order-*. */}
        <section className={`${panel} order-2 min-w-0 flex-1 lg:order-1`}>
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

        <section className={`${panel} order-1 w-full lg:order-2 lg:sticky lg:top-6 lg:w-80 lg:shrink-0`}>
          <h2 className={panelHeading}>Job</h2>
          <JobTray definition={definition} canSubmit={canSubmit(definition)} isRenderable={canSubmit} />
        </section>
      </div>
    </div>
  );
}
