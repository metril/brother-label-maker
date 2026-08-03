import { useEffect, useRef, useState } from "react";
import { pngDataUrl } from "../api/client";
import { useChainedPreview } from "../hooks/useChainedPreview";
import { useTapes } from "../hooks/useTapes";
import { useChainPreviewStore } from "../stores/chainPreview";
import { useCurrentDesignStore } from "../stores/currentDesign";
import { useTrayStore } from "../stores/tray";
import { CHAIN_MODE_OPTIONS } from "../lib/chainModes";
import { computeFeedDeckGeometry, DEFAULT_PX_PER_MM } from "../lib/feedDeckGeometry";
import { Pending } from "./ui/Pending";
import { SegmentedControl } from "./ui/SegmentedControl";
import { errorText, eyebrow, helpText, iconButtonClass } from "./ui/styles";
import type { ChainMode, LabelDefinition, PrintOptions } from "../api/types";

/** track C3-style zoom control -- unchanged from the old ChainedPreviewDialog
 * (see that component's own removed docstring in git history): the option's
 * own string IS the px-per-mm figure (`Number(zoom)` below), "4" matches
 * feedDeckGeometry.ts's own DEFAULT_PX_PER_MM so the strip opens at that
 * same default size. */
type ZoomLevel = "2" | "4" | "8";
const ZOOM_OPTIONS: { value: ZoomLevel; label: string }[] = [
  { value: "2", label: "2×" },
  { value: "4", label: "4×" },
  { value: "8", label: "8×" },
];

/** Track C2 rework: a WIDE right-side slide-over (not a centered modal --
 * see the deleted components/ChainedPreviewDialog.tsx) previewing the WHOLE
 * chained job as a single composited strip, reachable from every route
 * (including Design) via either components/TrayPanel.tsx instance's own
 * "Preview chain" button. Mounted exactly ONCE, in AppShell.tsx, outside
 * every translated ancestor (JobTray's own sidebar/sheet wrapper,
 * GlobalTrayDrawer's own slide-over wrapper both carry a CSS `translate`) --
 * `position: fixed` descendants of a translated ancestor are contained by
 * THAT ancestor's box instead of the viewport, which is exactly the bug the
 * old Dialog component sidestepped by portalling to `document.body`
 * (ui/Dialog.tsx's own docstring). Mounting here at AppShell level gets the
 * same correctness a body portal would, without one.
 *
 * Because it's mounted once, independent of whichever TrayPanel happens to
 * be visible, its own body/options/chain-mode are read directly off
 * stores/tray.ts -- exactly the same way components/GlobalTrayDrawer.tsx's
 * own header estimate already does -- rather than threaded down as props
 * the way the old dialog's `labels`/`options`/`serialization`/`isRenderable`
 * were. The one exception: the Designer page's "current, unsaved design"
 * lives only in Designer's render state, so pages/Designer.tsx mirrors it
 * into stores/currentDesign.ts (cleared on unmount) and an EMPTY tray falls
 * back to previewing that single design -- the exact fallback TrayPanel's
 * own bodyLabels/bodySerialization give the estimate and Print button,
 * serialization included. Off the Design route the mirror is null and an
 * empty tray shows "Nothing to preview".
 *
 * Open/close is stores/chainPreview.ts's `open` (shared with every
 * TrayPanel instance), not hooks/useDialogController.ts -- that hook owns
 * `isOpen` itself as local state, which can't react to a sibling subtree's
 * click. The focus/Escape contract below reimplements that hook's own
 * conventions (capture the trigger, move focus to the close button the
 * instant it opens, Escape closes, restore focus to the trigger on close)
 * against this externally-owned `open` instead.
 *
 * Permanently MOUNTED (visibility/translate-toggled below), not
 * conditionally unmounted -- same convention GlobalTrayDrawer's own panel
 * uses, and required here for the SAME reason `enabled: open && ...` in
 * hooks/useChainedPreview.ts still works right: staying mounted means
 * editing the tray while this drawer is open (add/remove/reorder) changes
 * `labels` on every render, which changes useChainedPreview's own query
 * key and live-refetches the preview -- exactly the same "in-flight state
 * survives" property GlobalTrayDrawer's own docstring describes, just for
 * a query instead of a WS-tracked print job.
 *
 * Dockable-preview feature: `docked` (stores/chainPreview.ts, persisted)
 * switches this SAME panel between that fixed-overlay behavior (unchanged
 * above) and a real in-flow right-hand column -- AppShell.tsx now mounts
 * this component as the LAST child of its content row specifically so a
 * docked panel has somewhere to sit in normal flow, beside `<main>`. Only
 * the panel's own classes/attributes switch (a single DOM node, no
 * conditional unmount) -- `docked`/`open` are both ordinary component
 * state, not viewport-dependent, so THOSE branches are plain JS
 * conditionals; only the actual per-breakpoint sizing stays Tailwind
 * `xl:`-prefixed classes (jsdom can't evaluate media queries, so any
 * viewport-dependent behavior has to stay class-based to be testable at
 * all -- the same rule this app's other responsive panels, e.g.
 * symbols/SymbolBrowser.tsx's own sidebar switch, already follow). Docked
 * mode swaps dialog semantics for a landmark (`role="complementary"`, no
 * `aria-modal`), drops the backdrop scrim entirely, and skips the
 * focus-steal/Escape-close/trigger-restore contract below (see the
 * dedicated effect for why `docked` sits in ITS OWN dependency array,
 * separate from the mode-resync effect) -- none of that modal machinery
 * belongs to an in-flow landmark a user can otherwise ignore. The close
 * button still works in every mode; below `xl` a docked panel simply falls
 * back to the same fixed-overlay positioning as undocked (just without the
 * scrim/modality), so docking is never a no-op even on a narrow viewport
 * that can't actually fit an in-flow column. */
export function ChainPreviewDrawer() {
  const open = useChainPreviewStore((s) => s.open);
  const closeDrawer = useChainPreviewStore((s) => s.closeDrawer);
  const docked = useChainPreviewStore((s) => s.docked);
  const toggleDocked = useChainPreviewStore((s) => s.toggleDocked);
  // Designer's mirrored "current, unsaved design" -- the empty-tray
  // fallback (see this file's docstring and stores/currentDesign.ts).
  const currentDesign = useCurrentDesignStore((s) => s.current);

  const items = useTrayStore((s) => s.items);
  const trayChainMode = useTrayStore((s) => s.chainMode);
  const autoCut = useTrayStore((s) => s.autoCut);
  // /api/tapes' full geometry catalog -- needed below (M10) to size the
  // strip off the tape's PRINT height, not its nominal width. Same source
  // Designer.tsx's own FeedDeck usage reads.
  const { data: tapes } = useTapes();

  const [mode, setMode] = useState<ChainMode>(trayChainMode);
  // DEFAULT_PX_PER_MM (4) as the drawer's opening zoom level -- reusing the
  // SAME constant feedDeckGeometry.ts's own "never derive mm from PNG
  // pixels" contract is built on, rather than a second, independently
  // chosen default.
  const [zoom, setZoom] = useState<ZoomLevel>(String(DEFAULT_PX_PER_MM) as ZoomLevel);

  const triggerRef = useRef<HTMLElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  function close() {
    closeDrawer();
    triggerRef.current?.focus?.();
    triggerRef.current = null;
  }

  // Re-seed `mode` from the tray's own chain mode whenever the drawer
  // opens -- guarded on `open` alone (not `trayChainMode`), same "never
  // clobber a tab the user already clicked mid-comparison" semantics the
  // old ChainedPreviewDialog's own effect had. Split out from the
  // focus/Escape effect below (dockable-preview feature) specifically so
  // toggling `docked` mid-open can never re-run THIS effect and stomp a
  // mode the user already picked.
  useEffect(() => {
    if (!open) return;
    setMode(trayChainMode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Focus/Escape modal contract: capture whatever triggered the open
  // (`document.activeElement` at the moment `open` flips true -- nothing
  // else moves focus between a trigger's own click handler and this effect
  // running, so it's reliably still the clicked button here), move focus
  // onto the close button, and wire Escape. Skipped entirely while `docked`
  // (dockable-preview feature): a docked panel is a landmark
  // (`role="complementary"` below), not a modal dialog, so it must never
  // steal focus off whatever the user's doing elsewhere on the page, or
  // swallow their Escape key. `docked` deliberately sits in this effect's
  // OWN dependency array (unlike the mode-resync effect above) -- toggling
  // dock mid-open needs this effect to tear down (remove the Escape
  // listener) the instant `docked` flips true, and re-arm itself if the
  // user undocks again while still open.
  useEffect(() => {
    if (!open || docked) return;
    triggerRef.current = document.activeElement as HTMLElement | null;
    closeButtonRef.current?.focus();
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") close();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, docked]);

  // Same body-composition rule as TrayPanel: a non-empty tray previews the
  // tray's own items (never silently mixing in the current design); an
  // empty tray falls back to Designer's mirrored current design when it's
  // submittable, serialization included. Tray items themselves never carry
  // a serialization run (a Designer-page, single-design concept).
  const trayHasItems = items.length > 0;
  const fallback = !trayHasItems && currentDesign !== null && currentDesign.canSubmit ? currentDesign : null;
  const labels: LabelDefinition[] = trayHasItems
    ? items.map((i) => i.definition)
    : fallback
      ? [fallback.definition]
      : [];
  const serialization = fallback ? fallback.serialization : null;
  const options: PrintOptions = { chain_mode: mode, margin_mm: 2.0, auto_cut: autoCut };

  function isRenderable(ls: LabelDefinition[]): boolean {
    return ls.length > 0;
  }

  const { preview, isFetching, error } = useChainedPreview(labels, options, isRenderable, serialization, open);

  const pxPerMm = Number(zoom);
  // All labels in a body share one tape (server-validated, see
  // router_print.py's _validate_and_measure) -- the nominal tape width is
  // therefore the same read off any one of them.
  const tapeWidthMm = labels[0]?.tape.width_mm ?? 0;
  // /api/tapes' matching row (nominal_mm+family exact match, same lookup
  // Designer.tsx does for FeedDeck's own tapeInfo prop) -- gives print_mm,
  // which LabelDefinition.tape itself doesn't carry (only width_mm/family).
  // null for the brief window before /api/tapes resolves (staleTime:
  // Infinity, so effectively once per session).
  const tapeInfo = tapes?.find((t) => t.family === labels[0]?.tape.family && t.nominal_mm === tapeWidthMm) ?? null;
  const lastSegment = preview && preview.segments.length > 0 ? preview.segments[preview.segments.length - 1]! : null;
  // UNIT TRAP (see ChainedPreviewResponse's own doc): the composite PNG's
  // own drawn content ends at the LAST segment's end_mm, NOT at
  // `preview.total_mm` -- total_mm additionally counts feed overhead
  // (margins, the trailing cut/feed allowance) that's never actually
  // painted into the image, so sizing the strip from it would stretch the
  // image past its own real content.
  const contentWidthMm = lastSegment?.end_mm ?? 0;
  // Reuse feedDeckGeometry's own printMm-based math (M10 review fix)
  // instead of a second, independently-derived height rule: the composite
  // PNG is drawn print_dots tall -- the PRINTABLE band (~18.1mm on 24mm
  // tape), not the tape's full nominal width -- so sizing the strip off
  // nominal (as this used to) stretched the image ~1.33x vertically vs.
  // FeedDeck's own (correct) strip. `minFeedMm: 0` is a throwaway: this
  // drawer has no feed-waste indicator, only `printableHeightPx` below is
  // read off the result. Falls back to the nominal width for printMm while
  // `tapeInfo` is still null (the brief pre-/api/tapes window above).
  const geo = computeFeedDeckGeometry(contentWidthMm, tapeWidthMm, tapeInfo?.print_mm ?? tapeWidthMm, 0, pxPerMm);
  const stripWidthPx = geo.stripWidthPx;
  const stripHeightPx = geo.printableHeightPx;

  const renderable = isRenderable(labels);

  return (
    <>
      {/* No scrim in docked mode (dockable-preview feature) -- a docked
          panel is an in-flow landmark, not a modal overlay, so nothing
          behind it should dim or click-to-close. */}
      {open && !docked && <div aria-hidden onClick={close} className="fixed inset-0 z-40 bg-scrim/70" />}

      {/* Always mounted (visibility/translate-toggled below) -- see this
          component's own docstring. Below `xl`, docked and undocked render
          IDENTICALLY (same fixed/translate overlay classes, just without
          the scrim/dialog semantics above/below when docked); the
          `docked && open` class group only kicks in at `xl:` and up, where
          it overrides position/translate/visibility back to an in-flow
          column -- see this component's own docstring for the full
          contract. `transition-transform` is dropped while `docked` so
          that override never animates as a slide (there's nothing to slide
          once the panel's back in normal flow). */}
      <div
        data-testid="chain-preview-drawer-panel"
        role={open ? (docked ? "complementary" : "dialog") : undefined}
        aria-modal={open && !docked ? true : undefined}
        aria-label={open ? "Print preview" : undefined}
        className={`fixed inset-y-0 right-0 z-50 flex w-[min(94vw,56rem)] flex-col gap-4 overflow-y-auto border-l border-deck-800 bg-deck-900 p-5 shadow-lg ${
          docked ? "" : "transition-transform duration-150 motion-reduce:transition-none"
        } ${open ? "visible translate-x-0" : "invisible translate-x-full"} ${
          docked && open
            ? "xl:static xl:inset-auto xl:z-auto xl:translate-x-0 xl:visible xl:w-[26rem] xl:shrink-0 xl:border-l"
            : ""
        }`}
      >
        <div className="flex items-center justify-between gap-2">
          <span className={eyebrow}>Print preview</span>
          <div className="flex items-center gap-1.5">
            {/* Dock/undock toggle (dockable-preview feature) -- house
                icon-button styling (iconButtonClass, same as the close
                button beside it), accessible name flips with the current
                state rather than describing the click (same convention as
                AppShell's own ThemeCycleButton). */}
            <button
              type="button"
              onClick={toggleDocked}
              aria-label={docked ? "Undock preview" : "Dock preview"}
              title={docked ? "Undock preview" : "Dock preview"}
              className={iconButtonClass}
            >
              <span aria-hidden="true">{docked ? "▣" : "▢"}</span>
            </button>
            <button
              type="button"
              ref={closeButtonRef}
              onClick={close}
              aria-label="Close chain preview"
              className={iconButtonClass}
            >
              ×
            </button>
          </div>
        </div>

        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <span className={`${eyebrow} mb-1.5 block`}>Chain mode</span>
            <SegmentedControl ariaLabel="Preview chain mode" value={mode} options={CHAIN_MODE_OPTIONS} onChange={setMode} />
            <p className={helpText}>{CHAIN_MODE_OPTIONS.find((o) => o.value === mode)?.description}</p>
          </div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-[11px] text-deck-400">Zoom</span>
            {/* "Print preview zoom", not "Preview zoom" (L14 review fix) --
                Designer.tsx's own zoom control shares that exact name, and
                both can legitimately be mounted at once (this drawer opens
                from the Design route too), which would otherwise give two
                same-named radiogroups on one page. */}
            <SegmentedControl ariaLabel="Print preview zoom" options={ZOOM_OPTIONS} value={zoom} onChange={setZoom} />
          </div>
        </div>

        <div>
          {!renderable ? (
            <p className="text-[13px] text-deck-400">Nothing to preview.</p>
          ) : error ? (
            <p role="alert" className={errorText}>
              {error}
            </p>
          ) : !preview ? (
            <div className="flex min-h-[120px] items-center justify-center">
              <Pending />
            </div>
          ) : (
            <>
              <div className="relative overflow-x-auto rounded-xl border border-deck-700 bg-deck-900 px-6 py-8">
                <div className="relative" style={{ width: stripWidthPx, height: stripHeightPx }}>
                  <img
                    src={pngDataUrl(preview.png_b64)}
                    alt="Chained job preview"
                    style={{ width: stripWidthPx, height: stripHeightPx, imageRendering: "pixelated" }}
                  />
                  {preview.segments.map((seg) => (
                    <span key={seg.index}>
                      <span
                        data-testid={`segment-chip-${seg.index}`}
                        className="absolute top-1 rounded-full border border-amber-500/50 bg-deck-900/80 px-1.5 py-0.5 font-mono text-[10px] leading-none text-amber-300"
                        style={{ left: seg.start_mm * pxPerMm + 4 }}
                      >
                        {seg.index + 1}
                      </span>
                      {/* Dashed cut-boundary line at this label's own end --
                          same visual convention as FeedDeck's own cut-line
                          (DeckStrip's cutLineXPx), one per segment so a
                          multi-label strip shows every boundary, not just
                          the composite's overall end. */}
                      <span
                        aria-hidden
                        data-testid={`segment-boundary-${seg.index}`}
                        className="absolute inset-y-0"
                        style={{ left: seg.end_mm * pxPerMm, borderLeft: "1.5px dashed var(--color-rust-500)" }}
                      />
                    </span>
                  ))}
                  {isFetching && (
                    <span aria-hidden className="pointer-events-none absolute inset-0 block animate-pulse bg-scrim/10" />
                  )}
                </div>
              </div>

              <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 font-mono text-[13px] text-deck-200">
                <div className="flex flex-col">
                  <dt className="text-[11px] text-deck-400">Total</dt>
                  <dd data-testid="preview-total-mm">{preview.total_mm.toFixed(1)} mm</dd>
                </div>
                <div className="flex flex-col">
                  <dt className="text-[11px] text-deck-400">Content / overhead</dt>
                  <dd>
                    {preview.content_mm.toFixed(1)} / {preview.feed_overhead_mm.toFixed(1)} mm
                  </dd>
                </div>
                <div className="flex flex-col">
                  <dt className="text-[11px] text-deck-400">Per label</dt>
                  <dd>{preview.per_label_mm.toFixed(1)} mm</dd>
                </div>
              </dl>

              {preview.notes.length > 0 && (
                <ul className="mt-2 flex flex-col gap-0.5 text-[11px] leading-snug text-deck-400">
                  {preview.notes.map((note, i) => (
                    <li key={i}>· {note}</li>
                  ))}
                </ul>
              )}

              {preview.warnings.length > 0 && (
                <ul className="mt-2 flex flex-col gap-1">
                  {preview.warnings.map((w, i) => (
                    <li key={i} role="alert" className="text-[12px] text-rust-500">
                      {w}
                    </li>
                  ))}
                </ul>
              )}

              <p className={helpText}>
                Tape usage shown here is an UNVERIFIED estimate pending the physical print checkpoint — actual
                feed/margin behavior on real hardware may differ.
              </p>
            </>
          )}
        </div>
      </div>
    </>
  );
}
