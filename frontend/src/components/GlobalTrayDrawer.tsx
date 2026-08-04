import { useEffect, useRef } from "react";
import { usePrintEstimate } from "../hooks/usePrintEstimate";
import { useCurrentDesignStore } from "../stores/currentDesign";
import { usePrintPreviewStore } from "../stores/printPreview";
import { useTrayDrawerStore } from "../stores/trayDrawer";
import { useTrayStore } from "../stores/tray";
import { useIsDesktop } from "../hooks/useIsDesktop";
import { TrayPanel } from "./TrayPanel";
import { eyebrow, iconButtonClass } from "./ui/styles";
import type { LabelDefinition, PrintOptions } from "../api/types";

/** Makes the print tray reachable from every route -- including the
 * Designer page ("/") -- via a header button ("Tray"/"Tray · N[, X.X mm]")
 * that toggles a right-side panel rendering components/TrayPanel.tsx.
 * The tray's own QUEUE (stores/tray.ts) is the same everywhere; the ONE
 * thing that differs by route is `current`, the Designer page's "current,
 * unsaved design" (stores/currentDesign.ts, written only by that page's
 * own mirror effect, `null` everywhere else) -- see TrayPanel's own
 * CurrentDesign doc for what that unlocks (an empty-tray print fallback,
 * "+ Add to tray"). The button is hidden when there's nothing to act on at
 * all (empty tray AND no current design) AND the panel is already closed --
 * nothing to occupy header space for otherwise (but never while its own
 * panel is open -- see GlobalTrayButton below).
 *
 * This file exports the trigger button and the panel SEPARATELY
 * (`GlobalTrayButton` / `GlobalTrayPanel`) instead of one combined
 * component -- AppShell.tsx mounts the button in the header and the panel
 * in its own subtree in the content row, so a single component gating both
 * behind one `useDialogController` doesn't fit. Open/close state lives in
 * stores/trayDrawer.ts (module-level, shared the same way
 * stores/printPreview.ts already is) instead of that hook's local state --
 * see that store's own docstring: ONE persisted `open` boolean, no
 * dock/undock choice. Whether an open panel reads as an in-flow column or a
 * modal overlay is purely breakpoint-driven (hooks/useIsDesktop.ts's
 * `DESKTOP_QUERY`, matching Tailwind's `xl`): at `xl` and up it's ALWAYS the
 * in-flow right column; below `xl` it's ALWAYS a modal overlay -- see
 * GlobalTrayPanel below. `GlobalTrayDrawer` below stays exported as a
 * compat wrapper rendering both, unchanged, for every call site that
 * doesn't care about the split (the Designer page's test harnesses, the
 * integration test inside PrintPreviewDeck.test.tsx).
 *
 * The panel stays permanently MOUNTED (visibility/transform-toggled, not
 * conditionally unmounted) -- exactly like PrintPreviewDeck's own panel,
 * and for the same reason: an in-flight print job's hooks/usePrintJob.ts
 * state (WS-tracked progress) must survive the panel closing. This means
 * the panel itself doesn't disappear just because the tray is empty and
 * there's no current design -- only the BUTTON hides in that case (see
 * GlobalTrayButton below); the panel simply renders hidden
 * (`invisible`/`translate-x-full`), the same resting state
 * PrintPreviewDeck's own panel already has with nothing to preview. */

/** The header trigger -- now a TOGGLE for the tray panel (previously
 * open-only): label text, the brief amber "tick" on a just-added item
 * (stores/tray.ts's own `lastAddedId`), the tape-estimate suffix once it
 * resolves, `aria-expanded` mirroring stores/trayDrawer.ts's `open`, and
 * hidden when there's nothing to act on AND the panel is already closed
 * (see the early return below for why "already closed" matters). Reads
 * stores/trayDrawer.ts's `toggle` instead of a local
 * `useDialogController` -- opening no longer needs to capture "what was
 * focused" itself: GlobalTrayPanel's own open effect below reads
 * `document.activeElement` at the moment it runs, the same decoupled
 * trigger-capture PrintPreviewDeck.tsx already relies on (nothing moves
 * focus between this button's click and that effect running). */
export function GlobalTrayButton() {
  const items = useTrayStore((s) => s.items);
  const chainMode = useTrayStore((s) => s.chainMode);
  const autoCut = useTrayStore((s) => s.autoCut);
  const lastAddedId = useTrayStore((s) => s.lastAddedId);
  const current = useCurrentDesignStore((s) => s.current);
  const open = useTrayDrawerStore((s) => s.open);
  const toggle = useTrayDrawerStore((s) => s.toggle);
  // Below-`xl` stacked-modal fix (see the onClick below): needed only to
  // gate that guard, not to change anything else about this button.
  const isDesktop = useIsDesktop();

  // Mirrors TrayPanel's own body derivation purely to summarize this
  // button's own estimate suffix -- deliberately duplicated rather than
  // lifted into a shared context: identical usePrintEstimate inputs share
  // the same react-query cache entry (app-wide, independent of where in
  // the tree each call happens), so this costs no extra request beyond
  // whatever TrayPanel itself already fetches while the drawer is open.
  const trayHasItems = items.length > 0;
  const bodyLabels: LabelDefinition[] = trayHasItems
    ? items.map((i) => i.definition)
    : current !== null
      ? [current.definition]
      : [];
  const bodySerialization = trayHasItems || current === null ? null : current.serialization;
  const options: PrintOptions = { chain_mode: chainMode, margin_mm: 2.0, auto_cut: autoCut };

  function isRenderableBody(labels: LabelDefinition[]): boolean {
    if (trayHasItems) return labels.length > 0;
    if (current === null) return false;
    return labels.length === 1 && current.isRenderable(labels[0]!);
  }

  const { estimate } = usePrintEstimate(bodyLabels, options, isRenderableBody, bodySerialization);

  // Rules of Hooks: every hook above must run on every render, so this
  // early return -- "hide when there's nothing to act on and the panel
  // isn't showing" -- comes last, after them, not before. Never hide the
  // trigger while its own panel is open: `open` is persisted (survives a
  // reload) and can outlive the tray going empty (e.g. printing empties it
  // while the panel is still open), so the panel must stay reachable to
  // close from wherever it's rendered.
  if (items.length === 0 && current === null && !open) return null;

  const label = items.length === 0 ? "Tray" : `Tray · ${items.length}`;
  const suffix = estimate ? `, ${estimate.total_mm.toFixed(1)} mm` : "";

  return (
    <button
      type="button"
      onClick={() => {
        // Event-driven (not an effect) -- only the OPEN direction needs a
        // guard here (closing this panel never conflicts with anything).
        // Doing it right here, synchronously in the click handler, means it
        // can't fight PrintPreviewDeck.tsx's own reconciliation EFFECT
        // (which closes THIS tray whenever the deck ends up open below
        // desktop -- see that effect's own comment for the full
        // mutual-exclusion contract, including why it's deliberately not
        // mirrored as a second effect here: a pair of reconciliation
        // effects would instead close BOTH panels on a both-open reload,
        // each one reacting to the other's `open` flipping true). Below
        // desktop, opening the tray while the preview deck happens to be
        // open closes the deck first, in this same click.
        if (!open && !isDesktop) usePrintPreviewStore.getState().closeDrawer();
        toggle();
      }}
      aria-haspopup="dialog"
      aria-expanded={open}
      className="rounded-md border border-deck-600 bg-deck-800 px-3 py-1.5 font-mono text-[12px] text-deck-200 transition-colors hover:border-deck-400"
    >
      {/* Brief "tick" on the count itself (stores/tray.ts's own
          `lastAddedId`, cleared 2s after an `addItem`) -- a plain
          transition-colors class swap fading amber -> deck-200, same
          mechanism/duration as TrayItemRow's own just-added highlight, so
          a user who adds from Homebox (or the Designer page itself) sees
          the count itself acknowledge the add even before opening the
          drawer. */}
      <span className={`transition-colors ${lastAddedId !== null ? "text-amber-300" : ""}`}>{label}</span>
      {suffix}
    </button>
  );
}

/** The panel -- reads stores/trayDrawer.ts directly instead of a
 * `dialog`/`useDialogController` prop. Overlay/in-flow semantics and the
 * focus/Escape contract are a direct port of PrintPreviewDeck.tsx's own
 * (see that component's own docstring for the full reasoning): below `xl`,
 * open is today's modal overlay (scrim, `role="dialog"`, `aria-modal`,
 * focus steal onto the close button, Escape closes, focus restores to the
 * trigger on close); at `xl` and up, open is a `role="complementary"`
 * landmark with none of that modal machinery, in-flow (`xl:static ...`);
 * closed is hidden at every width. `isDesktop` (hooks/useIsDesktop.ts, a
 * `DESKTOP_QUERY` media-query subscription) sits in the focus/Escape
 * effect's own dependency array for the same reason PrintPreviewDeck's
 * does: the viewport crossing `xl` mid-open must tear down (or re-arm) the
 * Escape listener immediately.
 *
 * `closeTrayDrawer` is only ever passed into TrayPanel BELOW `xl` -- see
 * TrayPanel's own prop doc for why it exists at all (closing this panel
 * the instant "Preview" opens PrintPreviewDeck, since both would
 * otherwise occupy the right edge at once). At `xl` the tray has nothing to
 * stack against in the first place: the preview deck becomes a full-width
 * band at the very bottom of the page at `xl` (see AppShell.tsx's own
 * docstring and PrintPreviewDeck.tsx's own), while the in-flow tray stays a
 * right-hand column above it -- the two occupy entirely different regions
 * of the screen. And even against a below-`xl` preview overlay, a pinned
 * tray should simply stay put while the user looks at a preview overlay,
 * not vanish out from under them. */
export function GlobalTrayPanel() {
  const open = useTrayDrawerStore((s) => s.open);
  const closeDrawer = useTrayDrawerStore((s) => s.closeDrawer);
  const isDesktop = useIsDesktop();
  const current = useCurrentDesignStore((s) => s.current);
  const addItem = useTrayStore((s) => s.addItem);

  const triggerRef = useRef<HTMLElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  function close() {
    closeDrawer();
    triggerRef.current?.focus?.();
    triggerRef.current = null;
  }

  // Always-on focus capture/restore -- ported verbatim from
  // PrintPreviewDeck.tsx's own identical effect (see that file's docstring
  // for the full reasoning). Runs at EVERY breakpoint, unlike the modal-only
  // effect below (which early-returns at desktop): without this, this
  // panel's own trigger (GlobalTrayButton) was never captured at `xl`, so
  // its × button dropped focus onto <body> on close instead of restoring
  // it. One addition specific to THIS panel: if the tray is emptied while
  // open and then closed, GlobalTrayButton itself unmounts (its own early
  // return above) before this effect's restore branch runs --
  // `triggerRef.current?.isConnected` is false in that case, so focus
  // simply falls back to <body>. Accepted: there's no trigger left to give
  // it back to.
  useEffect(() => {
    if (open) {
      triggerRef.current = document.activeElement as HTMLElement | null;
      return;
    }
    if (triggerRef.current?.isConnected) triggerRef.current.focus();
    triggerRef.current = null;
  }, [open]);

  // Focus/Escape modal contract -- ported verbatim from
  // PrintPreviewDeck.tsx's own effect (see that file's docstring for the
  // full reasoning): move focus onto the close button, wire Escape, all
  // skipped at `xl` and up (a landmark, not a modal, must never steal focus
  // or swallow Escape). Trigger capture/restore itself now lives in the
  // always-on effect above, so it isn't duplicated here.
  useEffect(() => {
    if (!open || isDesktop) return;
    closeButtonRef.current?.focus();
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") close();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, isDesktop]);

  // The snapshot logic behind "+ Add to tray" -- moved here verbatim from
  // pages/Designer.tsx (pre-unification, task 2.12): a DEEP COPY of the
  // current design's definition, so editing the form afterward never
  // retroactively changes the queued item.
  function handleAddToTray() {
    if (!current || !current.canSubmit) return;
    addItem({
      definition: structuredClone(current.definition),
      png: current.png,
      lengthMm: current.lengthMm,
      label: current.label,
    });
  }

  return (
    <>
      {/* No scrim at `xl` and up -- an in-flow panel there is a landmark,
          not a modal overlay, so nothing behind it should dim or
          click-to-close. */}
      {open && !isDesktop && <div aria-hidden onClick={close} className="fixed inset-0 z-40 bg-scrim/70" />}

      {/* Always mounted (visibility/translate-toggled below) -- see this
          file's own top-of-file docstring. Below `xl`, this renders
          IDENTICALLY regardless of `open`'s history; the second class group
          below (gated on `open` alone) only kicks in at `xl:` and up, where
          it switches this back to an in-flow column -- see
          PrintPreviewDeck.tsx's own docstring for the closest analogous
          contract (that panel becomes a bottom deck instead of a column at
          `xl`). This panel always gets its wrapping subtree's full height
          at `xl`: AppShell.tsx's own frame is viewport-bound (`h-screen` on
          its root column), so that subtree carries no explicit height of
          its own -- the content row's own `items-stretch` plus the root's
          definite height size it exactly, regardless of whether the
          preview deck below is separately open. Deliberately NOT
          `xl:shrink-0` (unlike PrintPreviewDeck's own `xl:` contract, which
          correctly IS shrink-0 -- it has an explicit `xl:h-64`): this panel
          has no explicit height of its own, so in the viewport-bound frame
          it must be allowed to shrink to whatever that subtree actually is.

          `xl:overflow-hidden` (overriding the base `overflow-y-auto`) --
          unlike below `xl`, where the WHOLE panel scrolling as one modal
          drawer is correct and unchanged, at `xl` the panel must fit its
          available height with NO panel-level scrolling: components/
          TrayPanel.tsx's own items list is the ONE region that scrolls
          there (`xl:min-h-0 xl:flex-1 xl:overflow-y-auto` on its scroller
          div), while its header and fixed-controls block (`xl:shrink-0`
          each) stay pinned. `xl:overflow-hidden` here is what stops THIS
          div from ALSO scrolling and fighting that inner scroller for the
          gesture. */}
      <div
        data-testid="global-tray-drawer-panel"
        role={open ? (isDesktop ? "complementary" : "dialog") : undefined}
        aria-modal={open && !isDesktop ? true : undefined}
        aria-label={open ? "Print tray" : undefined}
        className={`fixed inset-y-0 right-0 z-50 flex w-full max-w-sm flex-col gap-4 overflow-y-auto border-l border-deck-800 bg-deck-900 p-5 shadow-lg ${
          isDesktop ? "" : "transition-transform duration-150 motion-reduce:transition-none"
        } ${open ? "visible translate-x-0" : "invisible translate-x-full"} ${
          open
            ? // xl:max-w-none (M-review fix): the base `max-w-sm` (24rem)
              // above otherwise clamps this xl:-only width override, so the
              // desktop column rendered 24rem instead of the intended 26rem.
              // xl:overflow-hidden (fixed-panel fix): see this div's own
              // comment above -- overrides the base `overflow-y-auto` so the
              // panel itself never scrolls at `xl`; TrayPanel's own items
              // list is the only region that does. xl:gap-3 (height-budget
              // squeeze, tightens the base `gap-4` between this div's own
              // header/TrayPanel children) is part of the same live-measured
              // fix as TrayPanel.tsx's own `xl:gap-3`/disclosure/Mode-
              // description/Preview+Print compactions -- see that file's own
              // comment for the measured numbers.
              "xl:static xl:inset-auto xl:z-auto xl:translate-x-0 xl:visible xl:w-[26rem] xl:max-w-none xl:border-l xl:min-h-0 xl:overflow-hidden xl:gap-3"
            : ""
        }`}
      >
        <div className="flex items-center justify-between gap-2">
          <span className={eyebrow}>Tray</span>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              ref={closeButtonRef}
              onClick={close}
              aria-label="Close print tray"
              className={iconButtonClass}
            >
              ×
            </button>
          </div>
        </div>
        {/* `closeTrayDrawer` only below `xl` -- see this component's own
            docstring above for why the in-flow tray at `xl` never passes
            it. */}
        <TrayPanel current={current} onAddToTray={handleAddToTray} closeTrayDrawer={isDesktop ? undefined : close} />
      </div>
    </>
  );
}

/** Compat wrapper -- every call site that doesn't need the button/panel
 * split separately (Designer's own test harnesses, the integration test
 * inside PrintPreviewDeck.test.tsx) keeps rendering this unchanged.
 * AppShell.tsx itself mounts `GlobalTrayButton`/`GlobalTrayPanel`
 * separately instead, in different subtrees (header vs. rail). */
export function GlobalTrayDrawer() {
  return (
    <>
      <GlobalTrayButton />
      <GlobalTrayPanel />
    </>
  );
}
