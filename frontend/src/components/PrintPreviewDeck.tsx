import { useEffect, useRef, useState } from "react";
import { pngDataUrl } from "../api/client";
import { usePrintPreview } from "../hooks/usePrintPreview";
import { useTapes } from "../hooks/useTapes";
import { usePrintPreviewStore } from "../stores/printPreview";
import { useTrayStore } from "../stores/tray";
import { CHAIN_MODE_OPTIONS } from "../lib/chainModes";
import { computeFeedDeckGeometry, DEFAULT_PX_PER_MM } from "../lib/feedDeckGeometry";
import { Pending } from "./ui/Pending";
import { SegmentedControl } from "./ui/SegmentedControl";
import { errorText, eyebrow, helpText, iconButtonClass } from "./ui/styles";
import type { LabelDefinition, PrintOptions } from "../api/types";

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

/** The cycler row's previous/next buttons (Part 2: cycling through queued
 * labels) -- border/bg/text/rounded/transition lifted straight from
 * ui/styles.ts's own `segmentedButtonClass` (its unselected branch) so
 * these read as part of the same button family as every SegmentedControl
 * in this app, plus `iconButtonClass`'s own disabled treatment (these two
 * are plain actions with an end-of-list disabled state, not a persistent
 * radiogroup selection, so they stay ordinary buttons rather than becoming
 * a two-option SegmentedControl). */
const cyclerButtonClass =
  "flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-deck-600 bg-deck-800 text-[13px] font-medium text-deck-200 transition-colors hover:border-deck-400 disabled:cursor-not-allowed disabled:opacity-40";

/** Track C2 rework: a WIDE right-side slide-over (not a centered modal --
 * see the deleted components/ChainedPreviewDialog.tsx) previewing the WHOLE
 * chained job as a single composited strip, reachable from every route
 * (including Design) via TrayPanel.tsx's own "Preview" button.
 * Mounted exactly ONCE, in AppShell.tsx, outside every translated ancestor
 * (JobTray's own sidebar/sheet wrapper, GlobalTrayDrawer's own slide-over
 * wrapper both carry a CSS `translate`) -- `position: fixed` descendants of
 * a translated ancestor are contained by THAT ancestor's box instead of the
 * viewport, which is exactly the bug the old Dialog component sidestepped
 * by portalling to `document.body` (ui/Dialog.tsx's own docstring).
 * Mounting here at AppShell level gets the same correctness a body portal
 * would, without one. (Below `xl` -- and whenever undocked -- this remains
 * the ENTIRE story: a fixed-overlay slide-over, unchanged from Track C2.)
 *
 * Because it's mounted once, independent of whichever TrayPanel happens to
 * be visible, its own body/options are read directly off stores/tray.ts --
 * exactly the same way components/GlobalTrayDrawer.tsx's own header
 * estimate already does -- rather than threaded down as props the way the
 * old dialog's `labels`/`options`/`serialization`/`isRenderable` were.
 *
 * This deck previews the QUEUED PRINT JOB -- stores/tray.ts's own items,
 * and NOTHING else. It deliberately has no fallback to the Designer page's
 * "current, unsaved design" (stores/currentDesign.ts): that design-time
 * preview is pages/Designer.tsx's own embedded FeedDeck instead, the thing
 * a user is actively shaping before it's ever added to the tray. (TrayPanel
 * itself keeps that fallback for its estimate/Print button -- an empty tray
 * still prints/estimates the current design there -- this deck alone
 * stopped consuming it.) An EMPTY tray therefore always shows "Nothing
 * queued to print." here, on every route, regardless of what the Designer
 * page's own current design happens to be at the moment -- see the render
 * below.
 *
 * Mode unification: chain mode itself is read straight off
 * `useTrayStore.chainMode` -- no local copy, no re-seed-on-open effect.
 * TrayPanel.tsx's
 * own radiogroup is now the ONLY control that can change it, anywhere in
 * the app; this deck only ever shows a read-only label of the current
 * selection (`data-testid="deck-mode-label"`, next to the "Print preview"
 * eyebrow) so a docked deck stays self-describing even though the actual
 * control lives in a different subtree entirely. Switching modes from the
 * Tray still live-refetches this deck's own preview exactly as before --
 * `options.chain_mode` reads off the same store value, and that flows into
 * usePrintPreview's own query key same as any other tray edit.
 *
 * Open/close is stores/printPreview.ts's `open` (shared with every
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
 * hooks/usePrintPreview.ts still works right: staying mounted means editing
 * the tray while this deck is open (add/remove/reorder, or switching chain
 * mode from the Tray) changes `labels`/`options` on every render, which
 * changes usePrintPreview's own query key and live-refetches the preview --
 * exactly the same "in-flight state survives" property GlobalTrayDrawer's
 * own docstring describes, just for a query instead of a WS-tracked print
 * job.
 *
 * Dockable-preview feature: `docked` (stores/printPreview.ts, persisted)
 * switches this SAME panel between that fixed-overlay behavior (unchanged
 * above) and a real in-flow FULL-WIDTH BOTTOM DECK. No `position: sticky`
 * involved -- AppShell.tsx's own frame is viewport-bound (`h-screen` on its
 * root column; `<main>` scrolls internally instead), so this component,
 * mounted as the LAST child of that root column (below the header and the
 * `<main>`/dock-rail content row), is simply the root column's own last
 * in-flow child once docked+open makes it `xl:static`. Fixed at `xl:h-64`
 * (16rem) tall -- that figure is this component's own height alone now; no
 * other file needs to know it (AppShell.tsx's dock rail used to reserve a
 * matching `calc()` height for the tray, but that mechanism is gone --
 * flexbox alone sizes the rail now, see AppShell.tsx's own docstring).
 *
 * Only the panel's own classes/attributes switch (a single DOM node, no
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
 * dedicated effect's own comment for why `docked` sits in its dependency
 * array) -- none of that modal machinery belongs to an in-flow landmark a
 * user can otherwise ignore. The close
 * button still works in every mode; below `xl` a docked panel simply falls
 * back to the same fixed-overlay positioning as undocked (just without the
 * scrim/modality), so docking is never a no-op even on a narrow viewport
 * that can't actually fit a bottom deck.
 *
 * Three-group internal layout (docked-deck reshape): the panel's children
 * are wrapped into three sibling groups -- A (header + zoom), B (cycler +
 * strip), C (stats/notes/warnings/disclaimer) -- so that once `docked &&
 * open` flips the panel itself to `xl:flex-row`, A and C can take fixed
 * side columns (`xl:w-56`/`xl:w-72`) and B (the strip, the whole point of a
 * docked deck) gets the leftover width via `xl:flex-1`. Undocked/below-xl,
 * all three groups stack exactly as their un-grouped predecessors did.
 *
 * Cycling through queued labels: once a preview with 2+ segments is
 * loaded, a small previous/next row appears above the strip
 * (stores/printPreview.ts's own `selectedIndex`, shared the same way
 * `open`/`docked` are -- session-only, never persisted) and the currently
 * selected segment gets an amber highlight overlay on the strip itself,
 * positioned from the SAME mm-derived left/width math the segment
 * chips/boundary lines below already use (never the PNG's own pixel
 * dimensions -- see ChainedPreviewResponse's own UNIT TRAP doc). A single-
 * segment job renders neither row nor highlight; there's nothing to cycle
 * through. `selectedIndex` resets to 0 whenever the loaded preview's own
 * identity changes (a tray edit or a mode switch from the Tray changes the
 * underlying request, which can change which/how-many segments come back)
 * or the deck opens fresh -- see the dedicated effect below. */
export function PrintPreviewDeck() {
  const open = usePrintPreviewStore((s) => s.open);
  const closeDrawer = usePrintPreviewStore((s) => s.closeDrawer);
  const docked = usePrintPreviewStore((s) => s.docked);
  const toggleDocked = usePrintPreviewStore((s) => s.toggleDocked);
  const selectedIndex = usePrintPreviewStore((s) => s.selectedIndex);
  const setSelectedIndex = usePrintPreviewStore((s) => s.setSelectedIndex);

  const items = useTrayStore((s) => s.items);
  // Mode unification: the Tray's own chainMode is the ONLY mode state left
  // anywhere in the app (see this component's own docstring) -- no local
  // copy, no re-seed-on-open effect.
  const mode = useTrayStore((s) => s.chainMode);
  const autoCut = useTrayStore((s) => s.autoCut);
  // /api/tapes' full geometry catalog -- needed below (M10) to size the
  // strip off the tape's PRINT height, not its nominal width. Same source
  // Designer.tsx's own FeedDeck usage reads.
  const { data: tapes } = useTapes();

  // DEFAULT_PX_PER_MM (4) as the deck's opening zoom level -- reusing the
  // SAME constant feedDeckGeometry.ts's own "never derive mm from PNG
  // pixels" contract is built on, rather than a second, independently
  // chosen default.
  const [zoom, setZoom] = useState<ZoomLevel>(String(DEFAULT_PX_PER_MM) as ZoomLevel);

  const triggerRef = useRef<HTMLElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  // The strip's own horizontal-scroll container (cycling through queued
  // labels) -- scrolled to bring the selected segment into view whenever
  // `selectedIndex` moves, see the dedicated effect below.
  const stripContainerRef = useRef<HTMLDivElement>(null);

  function close() {
    closeDrawer();
    triggerRef.current?.focus?.();
    triggerRef.current = null;
  }

  // Focus/Escape modal contract: capture whatever triggered the open
  // (`document.activeElement` at the moment `open` flips true -- nothing
  // else moves focus between a trigger's own click handler and this effect
  // running, so it's reliably still the clicked button here), move focus
  // onto the close button, and wire Escape. Skipped entirely while `docked`
  // (dockable-preview feature): a docked panel is a landmark
  // (`role="complementary"` below), not a modal dialog, so it must never
  // steal focus off whatever the user's doing elsewhere on the page, or
  // swallow their Escape key. `docked` sits in this effect's own dependency
  // array (not just `open`) so that toggling dock mid-open tears down (or
  // re-arms) the Escape listener immediately, rather than leaving a stale
  // listener from before the toggle -- GlobalTrayDrawer.tsx's own
  // focus/Escape effect follows this identical shape for the same reason.
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

  // Labels come ONLY from the tray's own queued items -- this deck
  // previews the QUEUED PRINT JOB, never the Designer's in-progress,
  // unsaved design (see this component's own docstring). Tray items never
  // carry a serialization run (a Designer-page, single-design concept), so
  // there's no `serialization` to thread into usePrintPreview at all.
  const labels: LabelDefinition[] = items.map((i) => i.definition);
  const options: PrintOptions = { chain_mode: mode, margin_mm: 2.0, auto_cut: autoCut };

  function isRenderable(ls: LabelDefinition[]): boolean {
    return ls.length > 0;
  }

  const { preview, isFetching, error } = usePrintPreview(labels, options, isRenderable, open);

  // Cycling through queued labels: `selectedIndex` always starts back at 0
  // for a freshly loaded preview -- reset it whenever the thing actually
  // being previewed changes identity (a tray edit or chain-mode switch
  // changes `bodyKey`, which changes what comes back) or the deck opens
  // fresh (re-opening after leaving a PREVIOUS job on label 3 must not
  // silently reopen on label 3 of a different job). `preview?.segments
  // .length` rides along as a belt-and-braces signal alongside `bodyKey`
  // itself. `setSelectedIndex` is a stable zustand action reference, safe
  // to omit.
  const bodyKey = JSON.stringify({ labels, options });
  useEffect(() => {
    setSelectedIndex(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, bodyKey, preview?.segments.length]);

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
  // deck has no feed-waste indicator, only `printableHeightPx` below is
  // read off the result. Falls back to the nominal width for printMm while
  // `tapeInfo` is still null (the brief pre-/api/tapes window above).
  const geo = computeFeedDeckGeometry(contentWidthMm, tapeWidthMm, tapeInfo?.print_mm ?? tapeWidthMm, 0, pxPerMm);
  const stripWidthPx = geo.stripWidthPx;
  const stripHeightPx = geo.printableHeightPx;

  const renderable = isRenderable(labels);

  // Cycler status text's own name: the tray item's own caption when the
  // tray maps 1:1 onto the returned segments (the common case), else a
  // plain positional fallback -- see this component's own docstring on
  // `selectedIndex` for why a mismatch can happen at all (an in-flight
  // tray edit can arrive between a request and its response).
  function segmentName(index: number): string {
    if (preview && items.length === preview.segments.length) {
      return items[index]?.label ?? `Label ${index + 1}`;
    }
    return `Label ${index + 1}`;
  }

  // Scrolls the strip's own horizontal-scroll container so the newly
  // selected segment stays in view -- guarded with optional chaining
  // (pages/Designer.tsx's own scrollIntoView guard follows the same "not
  // every test/legacy environment implements this" convention) since jsdom
  // has no real layout engine and may not expose `scrollTo` at all. Skipped
  // entirely below 2 segments -- nothing to scroll TO when there's no
  // cycler in the first place.
  useEffect(() => {
    if (!preview || preview.segments.length < 2) return;
    const seg = preview.segments[selectedIndex];
    const container = stripContainerRef.current;
    if (!seg || !container) return;
    container.scrollTo?.({ left: seg.start_mm * pxPerMm, behavior: "smooth" });
  }, [selectedIndex, preview, pxPerMm]);

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
          it overrides position/translate/visibility/flow-direction back
          into a full-width, in-flow row that settles at the viewport
          bottom on its own (no sticky/fixed positioning involved) -- see
          this component's own docstring for the full contract. `transition-
          transform` is dropped while `docked` so that override never
          animates as a slide (there's nothing to slide once the panel's
          back in normal flow). */}
      <div
        data-testid="print-preview-deck-panel"
        role={open ? (docked ? "complementary" : "dialog") : undefined}
        aria-modal={open && !docked ? true : undefined}
        aria-label={open ? "Print preview" : undefined}
        className={`fixed inset-y-0 right-0 z-50 flex w-[min(94vw,56rem)] flex-col gap-4 overflow-y-auto border-l border-deck-800 bg-deck-900 p-5 shadow-lg ${
          docked ? "" : "transition-transform duration-150 motion-reduce:transition-none"
        } ${open ? "visible translate-x-0" : "invisible translate-x-full"} ${
          docked && open
            ? // No sticky, no calc() -- AppShell.tsx's own frame is
              // viewport-bound (`h-screen` root column), so this panel just
              // needs to be a plain in-flow block (`xl:static`) to land at
              // the viewport bottom on its own, the same shape the tray's
              // own docked contract (GlobalTrayDrawer.tsx) already uses.
              // `xl:h-64` is this component's own height alone now -- no
              // other file needs to know the figure.
              "xl:static xl:inset-auto xl:z-auto xl:h-64 xl:w-full xl:translate-x-0 xl:visible xl:shrink-0 xl:border-l-0 xl:border-t xl:flex-row xl:items-stretch xl:overflow-hidden xl:gap-5"
            : ""
        }`}
      >
        {/* Group A: header row (eyebrow + read-only mode label + dock/
            close buttons) + the zoom control row -- a fixed narrow column
            at `xl` while docked (this group never needs the strip's own
            width). `flex flex-col gap-4` internally reproduces the 1rem
            gap these two rows got for free as top-level panel children
            before this wrapper existed -- the panel's own `gap-4` now only
            separates the three top-level groups from each other, not the
            rows within them. */}
        <div className={`flex flex-col gap-4 ${docked && open ? "xl:w-56 xl:shrink-0" : ""}`}>
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className={eyebrow}>Print preview</span>
              {/* Read-only mode label (mode unification) -- this deck no
                  longer owns a mode control of its own; TrayPanel.tsx's
                  own radiogroup is the ONLY place chain mode can be
                  changed (see useTrayStore.chainMode above). This just
                  keeps a docked deck self-describing about which mode
                  it's currently rendering, without duplicating the
                  control itself. */}
              <span className="font-mono text-[11px] text-deck-400" data-testid="deck-mode-label">
                {CHAIN_MODE_OPTIONS.find((o) => o.value === mode)?.label}
              </span>
            </div>
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
                aria-label="Close print preview"
                className={iconButtonClass}
              >
                ×
              </button>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="font-mono text-[11px] text-deck-400">Zoom</span>
            {/* "Print preview zoom", not "Preview zoom" (L14 review fix) --
                Designer.tsx's own zoom control shares that exact name, and
                both can legitimately be mounted at once (this deck opens
                from the Design route too), which would otherwise give two
                same-named radiogroups on one page. */}
            <SegmentedControl ariaLabel="Print preview zoom" options={ZOOM_OPTIONS} value={zoom} onChange={setZoom} />
          </div>
        </div>

        {/* Group B: the cycler row + the strip itself (or, before a
            preview exists, whichever placeholder state applies) -- the
            strip is the whole point of a docked bottom deck, so it's the
            one group that actually grows (`xl:flex-1`) to fill the
            leftover width once A and C take their fixed columns.
            `xl:min-h-0 xl:overflow-y-auto` (review fix): the docked deck's
            own inner height is fixed (`xl:h-64`, 16rem, minus Group A/C's
            padding leaves ~216px), and at high zoom (8x) the cycler row +
            strip can exceed that -- without `xl:min-h-0` this flex child
            would refuse to shrink below its content's intrinsic height, and
            the overflow gets clipped by the panel's own `xl:overflow-hidden`
            (the outer docked class group) with no way to reach the clipped
            part; `xl:overflow-y-auto` gives Group B its own scroll escape
            instead of silently clipping content. */}
        <div
          className={`flex flex-col ${docked && open ? "xl:min-w-0 xl:flex-1 xl:flex xl:flex-col xl:min-h-0 xl:overflow-y-auto" : ""}`}
        >
          {!renderable ? (
            <div className="flex flex-col gap-1">
              <p className="text-[13px] text-deck-400">Nothing queued to print.</p>
              <p className={helpText}>Add labels to the tray to preview the job.</p>
            </div>
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
              {/* Cycling through queued labels (Part 2) -- only once there's
                  something to cycle THROUGH; a single-segment job renders
                  nothing here, same as the highlight overlay below. Clamped
                  at both ends via both the disabled attribute AND the
                  Math.max/min in the click handlers themselves, so neither
                  a stray click nor a double-fire can walk past either end. */}
              {preview.segments.length >= 2 && (
                <div className="flex items-center justify-center gap-3" data-testid="segment-cycler">
                  <button
                    type="button"
                    onClick={() => setSelectedIndex(Math.max(0, selectedIndex - 1))}
                    disabled={selectedIndex === 0}
                    aria-label="Previous label"
                    className={cyclerButtonClass}
                  >
                    <span aria-hidden="true">‹</span>
                  </button>
                  <span className="font-mono text-[12px] text-deck-200" data-testid="segment-cycler-status">
                    {selectedIndex + 1} of {preview.segments.length} — {segmentName(selectedIndex)}
                  </span>
                  <button
                    type="button"
                    onClick={() => setSelectedIndex(Math.min(preview.segments.length - 1, selectedIndex + 1))}
                    disabled={selectedIndex === preview.segments.length - 1}
                    aria-label="Next label"
                    className={cyclerButtonClass}
                  >
                    <span aria-hidden="true">›</span>
                  </button>
                </div>
              )}

              <div
                ref={stripContainerRef}
                className="relative overflow-x-auto rounded-xl border border-deck-700 bg-deck-900 px-6 py-8"
              >
                <div className="relative" style={{ width: stripWidthPx, height: stripHeightPx }}>
                  <img
                    src={pngDataUrl(preview.png_b64)}
                    alt="Print preview strip"
                    style={{ width: stripWidthPx, height: stripHeightPx, imageRendering: "pixelated" }}
                  />
                  {/* Selected-segment highlight -- left/width from the SAME
                      mm * pxPerMm math the chips/boundary lines below use
                      (never the PNG's own pixel dimensions, see this
                      component's own UNIT TRAP note). pointer-events-none:
                      purely decorative, must never intercept clicks meant
                      for whatever's underneath it. */}
                  {preview.segments.length >= 2 && preview.segments[selectedIndex] && (
                    <span
                      aria-hidden
                      data-testid="segment-highlight"
                      className="pointer-events-none absolute inset-y-0 rounded-sm ring-2 ring-amber-500 bg-amber-500/15"
                      style={{
                        left: preview.segments[selectedIndex]!.start_mm * pxPerMm,
                        width:
                          (preview.segments[selectedIndex]!.end_mm - preview.segments[selectedIndex]!.start_mm) *
                          pxPerMm,
                      }}
                    />
                  )}
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
            </>
          )}
        </div>

        {/* Group C: stats + notes + warnings + disclaimer -- only ever
            rendered alongside the strip (same three-part guard as Group
            B's own ternary), so it gets its own top-level conditional
            rather than living inside Group B. `mt-3` dropped from the
            `<dl>` below (it used to supply the gap between the strip and
            the stats when both lived in one unwrapped block container) --
            the panel's own top-level `gap-4` now supplies that same gap
            between Group B and Group C directly, so keeping `mt-3` too
            would double it. */}
        {renderable && !error && preview && (
          <div className={`flex flex-col ${docked && open ? "xl:w-72 xl:shrink-0 xl:overflow-y-auto" : ""}`}>
            <dl className="flex flex-wrap gap-x-6 gap-y-1 font-mono text-[13px] text-deck-200">
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
          </div>
        )}
      </div>
    </>
  );
}
