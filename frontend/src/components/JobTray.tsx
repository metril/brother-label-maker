import { useEffect, useRef, useState } from "react";
import { usePrintEstimate } from "../hooks/usePrintEstimate";
import { useTrayStore } from "../stores/tray";
import { TrayPanel, type CurrentDesign } from "./TrayPanel";
import { eyebrow, iconButtonClass, panelHeading } from "./ui/styles";
import type { LabelDefinition, PrintOptions } from "../api/types";

// Re-exported for compat: every existing import site/test wrote
// `import { JobTray, type CurrentDesign } from "./JobTray"` back when this
// file owned the type directly -- it now lives in TrayPanel.tsx (task
// 2.12's extraction, see that file's own doc), the ONE place both this
// component and components/GlobalTrayDrawer.tsx import it from.
export type { CurrentDesign };

interface JobTrayProps {
  current: CurrentDesign;
  onAddToTray: () => void;
}

/** The design doc's "JOB TRAY (sticky, estimate, chain mode, print)" --
 * Designer-only now: this component owns just the Designer page's own
 * responsive SHELL around the tray (a normal sticky sidebar at `lg:` and
 * above, a `position: fixed` bottom sheet below that), while the tray's
 * actual CONTENT (item list, chain mode/estimate/print) lives in
 * components/TrayPanel.tsx -- shared verbatim with
 * components/GlobalTrayDrawer.tsx, which reaches the SAME tray from every
 * OTHER route via a right-side slide-over instead of this sidebar/sheet.
 *
 * Renders its OWN full responsive shell (not wrapped by pages/Designer.tsx
 * the way it used to be): a normal sticky sidebar at `lg:` and above, and a
 * `position: fixed` bottom sheet below that -- ONE mounted content tree
 * either way (see the return statement's own comment), so there is never a
 * second, simultaneously-accessible "Print" button to disambiguate in
 * tests or for a screen reader. */
export function JobTray({ current, onAddToTray }: JobTrayProps) {
  const items = useTrayStore((s) => s.items);
  const chainMode = useTrayStore((s) => s.chainMode);
  const autoCut = useTrayStore((s) => s.autoCut);

  const [mobileExpanded, setMobileExpanded] = useState(false);
  // Review fix-up (a11y): the mobile sheet needs real dialog focus
  // handling, not just a visual slide-up -- `triggerRef` remembers whatever
  // had focus before it opened (the compact bar itself, in practice) so it
  // can be restored on close, and `closeButtonRef` is where focus MOVES to
  // the instant it opens, so a keyboard/screen-reader user lands inside the
  // sheet rather than still "behind" it. A full focus TRAP (Tab wrapping
  // back to the first/last element) is deliberately not implemented -- the
  // brief's own review called that optional -- but placement in/out is not.
  const triggerRef = useRef<HTMLElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);

  function openMobileSheet() {
    triggerRef.current = document.activeElement as HTMLElement | null;
    setMobileExpanded(true);
  }

  function closeMobileSheet() {
    setMobileExpanded(false);
    triggerRef.current?.focus?.();
    triggerRef.current = null;
  }

  useEffect(() => {
    if (!mobileExpanded) return;
    closeButtonRef.current?.focus();
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") closeMobileSheet();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [mobileExpanded]);

  // The compact mobile bar below needs its OWN copy of the estimate/item
  // count TrayPanel computes internally (it renders outside that always-
  // mounted panel, as a separate always-visible-on-mobile trigger). Mirrors
  // TrayPanel's own body derivation exactly -- deliberately duplicated
  // rather than lifted into a shared context: components/GlobalTrayDrawer.tsx
  // independently derives the same shape for its own header-button summary,
  // and every one of these calls shares usePrintEstimate's query cache (same
  // queryKey => the same in-flight/cached request), so this costs no extra
  // network round trip in practice.
  const trayHasItems = items.length > 0;
  const bodyLabels: LabelDefinition[] = trayHasItems ? items.map((i) => i.definition) : [current.definition];
  const bodySerialization = trayHasItems ? null : current.serialization;
  const options: PrintOptions = { chain_mode: chainMode, margin_mm: 2.0, auto_cut: autoCut };

  function isRenderableBody(labels: LabelDefinition[]): boolean {
    if (trayHasItems) return labels.length > 0;
    return labels.length === 1 && current.isRenderable(labels[0]!);
  }

  const { estimate } = usePrintEstimate(bodyLabels, options, isRenderableBody, bodySerialization);

  const itemCountLabel = trayHasItems
    ? `${items.length} item${items.length === 1 ? "" : "s"} queued`
    : "1 label (current design)";

  return (
    <>
      {/* ONE mounted content tree for both breakpoints: a normal sticky
          sidebar at lg: and above (position: sticky, in the flex row pages/
          Designer.tsx places this in), a `position: fixed` bottom sheet
          below that -- transformed off-screen until tapped open. Mounting
          the SAME tree twice (a separate always-visible desktop copy plus a
          separate sheet copy) would mean two simultaneously-accessible
          "Print" buttons any time the sheet is open, breaking exact-name
          queries (`getByRole("button", {name: "Print"})`) both in this
          task's own tests and Designer.serialize.test.tsx's pre-existing
          ones.

          `invisible`/`visible` (CSS `visibility`, NOT the `translate`
          transform above) is what actually keeps this out of the
          accessibility tree and tab order while collapsed on a small
          viewport -- a transform alone moves it off-screen but leaves it
          fully focusable/announced, which would otherwise hand a keyboard
          or screen-reader user a SECOND "Print" control any time the sheet
          is collapsed. `lg:visible` unconditionally overrides at the
          sticky-sidebar breakpoint, where this is always meant to be
          present regardless of `mobileExpanded`.

          `role="dialog"`/`aria-modal` are applied only while `mobileExpanded`
          -- this same div is the plain (non-dialog) desktop sidebar
          otherwise, and `lg:sticky` is the ONLY positioning intent there
          (a stray lg-prefixed `static` alongside it, from the first version
          of this component, was a genuine contradiction -- Tailwind's
          generated CSS order decides which wins, not the order written
          here; the class is also spelled dash-joined in this comment so
          Tailwind's source scanner doesn't emit a dead rule for it). Focus
          moves onto the close button the instant the sheet opens (see the
          effect above) and returns to whatever triggered it on close --
          `closeMobileSheet` is the ONLY way this component closes the
          sheet (× button, backdrop click, Escape) so that restoration is
          never skipped. */}
      <div
        data-testid="job-tray-panel"
        role={mobileExpanded ? "dialog" : undefined}
        aria-modal={mobileExpanded ? true : undefined}
        aria-label={mobileExpanded ? "Job tray" : undefined}
        className={`flex w-full flex-col gap-4 lg:order-2 lg:w-80 lg:shrink-0 fixed inset-x-0 bottom-14 z-50 max-h-[75vh] overflow-y-auto rounded-t-xl border-t border-deck-700 bg-deck-900 p-5 shadow-lg transition-transform duration-150 motion-reduce:transition-none ${
          mobileExpanded ? "visible translate-y-0" : "invisible translate-y-[120%]"
        } lg:visible lg:sticky lg:top-6 lg:z-auto lg:max-h-none lg:translate-y-0 lg:overflow-visible lg:rounded-xl lg:border lg:border-deck-800 lg:bg-deck-900/60 lg:p-5 lg:shadow-none`}
      >
        <div className="flex items-center justify-between lg:hidden">
          <span className={eyebrow}>Job</span>
          <button
            type="button"
            ref={closeButtonRef}
            onClick={closeMobileSheet}
            aria-label="Close job tray"
            className={iconButtonClass}
          >
            ×
          </button>
        </div>
        <h2 className={`${panelHeading} hidden lg:block`}>Job</h2>
        <TrayPanel current={current} onAddToTray={onAddToTray} />
      </div>

      {mobileExpanded && (
        <div aria-hidden onClick={closeMobileSheet} className="fixed inset-0 z-40 bg-scrim/70 lg:hidden" />
      )}

      <button
        type="button"
        data-testid="job-tray-mobile-bar"
        onClick={openMobileSheet}
        aria-label={`Open job tray — ${itemCountLabel}${estimate ? `, ${estimate.total_mm.toFixed(1)} millimeters` : ""}`}
        className="fixed inset-x-0 bottom-0 z-30 flex items-center justify-between gap-3 border-t border-deck-800 bg-deck-900 px-4 py-3 lg:hidden"
      >
        <span className="flex flex-col items-start gap-0.5">
          <span className="font-mono text-[16px] leading-none text-deck-200">
            {estimate ? `${estimate.total_mm.toFixed(1)} mm` : "···"}
          </span>
          <span className="text-[11px] text-deck-400">{itemCountLabel} · tap for details</span>
        </span>
        <span className="rounded-md border border-amber-500 bg-amber-500 px-4 py-1.5 text-[13px] font-semibold text-on-accent">
          Print
        </span>
      </button>
    </>
  );
}
