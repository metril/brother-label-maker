import { useEffect, useRef } from "react";
import { usePrintEstimate } from "../hooks/usePrintEstimate";
import { useCurrentDesignStore } from "../stores/currentDesign";
import { useTrayDrawerStore } from "../stores/trayDrawer";
import { useTrayStore } from "../stores/tray";
import { TrayPanel } from "./TrayPanel";
import { eyebrow, iconButtonClass } from "./ui/styles";
import type { LabelDefinition, PrintOptions } from "../api/types";

/** Makes the print tray reachable from every route -- including the
 * Designer page ("/") -- via a header button ("Tray"/"Tray · N[, X.X mm]")
 * that opens a right-side slide-over rendering components/TrayPanel.tsx.
 * The tray's own QUEUE (stores/tray.ts) is the same everywhere; the ONE
 * thing that differs by route is `current`, the Designer page's "current,
 * unsaved design" (stores/currentDesign.ts, written only by that page's
 * own mirror effect, `null` everywhere else) -- see TrayPanel's own
 * CurrentDesign doc for what that unlocks (an empty-tray print fallback,
 * "+ Add to tray"). The button is hidden entirely when there's nothing to
 * act on at all (empty tray AND no current design) -- nothing to occupy
 * header space for otherwise.
 *
 * Dockable-tray feature: this file now exports the trigger button and the
 * panel SEPARATELY (`GlobalTrayButton` / `GlobalTrayPanel`) instead of one
 * combined component, the same split components/PrintPreviewDeck.tsx's
 * own docking work established -- AppShell.tsx mounts the button in the
 * header and the panel inside its own dock rail (a different subtree
 * entirely once docked), so a single component gating both behind one
 * `useDialogController` no longer fits. Open/close/dock state lives in
 * stores/trayDrawer.ts (module-level, shared the same way
 * stores/printPreview.ts already is) instead of that hook's local state --
 * see that store's own docstring. `GlobalTrayDrawer` below stays exported
 * as a compat wrapper rendering both, unchanged, for every call site that
 * doesn't care about the split (the Designer page's test harnesses, the
 * integration test inside PrintPreviewDeck.test.tsx).
 *
 * The panel stays permanently MOUNTED (visibility/transform-toggled, not
 * conditionally unmounted) -- exactly like PrintPreviewDeck's own panel,
 * and for the same reason: an in-flight print job's hooks/usePrintJob.ts
 * state (WS-tracked progress) must survive the drawer closing. Unlike the
 * OLD combined component, this means the panel itself no longer disappears
 * just because the tray is empty and there's no current design -- only the
 * BUTTON hides in that case now (see GlobalTrayButton below); the panel
 * simply renders hidden (`invisible`/`translate-x-full`), the same resting
 * state PrintPreviewDeck's own panel already has with nothing to preview. */

/** The header trigger -- unchanged behavior from the pre-split component:
 * label text, the brief amber "tick" on a just-added item
 * (stores/tray.ts's own `lastAddedId`), the tape-estimate suffix once it
 * resolves, and hidden entirely when there's nothing to act on. Reads
 * stores/trayDrawer.ts's `openDrawer` instead of a local
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
  const openDrawer = useTrayDrawerStore((s) => s.openDrawer);

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
  // early return -- "hide entirely when there's nothing to act on" --
  // comes last, after them, not before.
  if (items.length === 0 && current === null) return null;

  const label = items.length === 0 ? "Tray" : `Tray · ${items.length}`;
  const suffix = estimate ? `, ${estimate.total_mm.toFixed(1)} mm` : "";

  return (
    <button
      type="button"
      onClick={openDrawer}
      aria-haspopup="dialog"
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
 * `dialog`/`useDialogController` prop. Overlay/docked semantics and the
 * focus/Escape contract are a direct port of PrintPreviewDeck.tsx's own
 * (see that component's own docstring for the full reasoning): undocked +
 * open is today's modal slide-over (scrim, `role="dialog"`, `aria-modal`,
 * focus steal onto the close button, Escape closes, focus restores to the
 * trigger on close); docked + open is a `role="complementary"` landmark
 * with none of that modal machinery, in-flow at `xl:` and up
 * (`xl:static ...`) and still a fixed non-modal overlay below it; closed is
 * hidden in both modes. `docked` sits in the focus/Escape effect's own
 * dependency array for the same reason PrintPreviewDeck's does: toggling
 * dock mid-open must tear down (or re-arm) the Escape listener immediately.
 *
 * `closeTrayDrawer` is only ever passed into TrayPanel while UNDOCKED --
 * see TrayPanel's own prop doc for why it exists at all (closing this panel
 * the instant "Preview" opens PrintPreviewDeck, since both would
 * otherwise occupy the right edge at once). A DOCKED tray has nothing to
 * stack against in the first place: the preview deck docks as a full-width
 * band at the very bottom of the page (see AppShell.tsx's own docstring
 * and PrintPreviewDeck.tsx's own), while a docked tray stays a right-hand
 * column in the dock rail above it -- the two occupy entirely different
 * regions of the screen. And even against an UNDOCKED preview, a pinned
 * tray should simply stay put while the user looks at a preview overlay,
 * not vanish out from under them. */
export function GlobalTrayPanel() {
  const open = useTrayDrawerStore((s) => s.open);
  const closeDrawer = useTrayDrawerStore((s) => s.closeDrawer);
  const docked = useTrayDrawerStore((s) => s.docked);
  const toggleDocked = useTrayDrawerStore((s) => s.toggleDocked);
  const current = useCurrentDesignStore((s) => s.current);
  const addItem = useTrayStore((s) => s.addItem);

  const triggerRef = useRef<HTMLElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  function close() {
    closeDrawer();
    triggerRef.current?.focus?.();
    triggerRef.current = null;
  }

  // Focus/Escape modal contract -- ported verbatim from
  // PrintPreviewDeck.tsx's own effect (see that file's docstring for the
  // full reasoning): capture whatever triggered the open, move focus onto
  // the close button, wire Escape, all skipped while `docked` (a landmark,
  // not a modal, must never steal focus or swallow Escape).
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
      {/* No scrim in docked mode -- a docked panel is an in-flow landmark,
          not a modal overlay, so nothing behind it should dim or
          click-to-close. */}
      {open && !docked && <div aria-hidden onClick={close} className="fixed inset-0 z-40 bg-scrim/70" />}

      {/* Always mounted (visibility/translate-toggled below) -- see this
          file's own top-of-file docstring. Below `xl`, docked and undocked
          render IDENTICALLY; the `docked && open` class group only kicks in
          at `xl:` and up, where it switches this back to an in-flow column
          -- see PrintPreviewDeck.tsx's own docstring for the closest
          analogous contract (that panel becomes a bottom deck instead of a
          column, since it docks independently now). This panel always gets
          the dock rail's full height while docked: AppShell.tsx's own frame
          is viewport-bound (`h-screen` on its root column), so the rail
          itself carries no explicit height -- the content row's own
          `items-stretch` plus the root's definite height size it exactly,
          regardless of whether the preview deck below is separately
          docked. Deliberately NOT `xl:shrink-0` (unlike PrintPreviewDeck's
          own docked contract, which correctly IS shrink-0 -- it has an
          explicit `xl:h-64`): this panel has no explicit height of its own,
          so in the viewport-bound frame it must be allowed to shrink to
          whatever the rail actually is, letting its own base
          `overflow-y-auto` scroll a tall tray internally -- `xl:shrink-0`
          here would instead let it overflow the rail and grow the page
          past the viewport, defeating the whole point of `h-screen`. */}
      <div
        data-testid="global-tray-drawer-panel"
        role={open ? (docked ? "complementary" : "dialog") : undefined}
        aria-modal={open && !docked ? true : undefined}
        aria-label={open ? "Print tray" : undefined}
        className={`fixed inset-y-0 right-0 z-50 flex w-full max-w-sm flex-col gap-4 overflow-y-auto border-l border-deck-800 bg-deck-900 p-5 shadow-lg ${
          docked ? "" : "transition-transform duration-150 motion-reduce:transition-none"
        } ${open ? "visible translate-x-0" : "invisible translate-x-full"} ${
          docked && open ? "xl:static xl:inset-auto xl:z-auto xl:translate-x-0 xl:visible xl:w-[26rem] xl:border-l xl:min-h-0" : ""
        }`}
      >
        <div className="flex items-center justify-between gap-2">
          <span className={eyebrow}>Tray</span>
          <div className="flex items-center gap-1.5">
            {/* Dock/undock toggle -- house icon-button styling
                (iconButtonClass, same as the close button beside it),
                mirroring PrintPreviewDeck's own dock button exactly. */}
            <button
              type="button"
              onClick={toggleDocked}
              aria-label={docked ? "Undock tray" : "Dock tray"}
              title={docked ? "Undock tray" : "Dock tray"}
              className={iconButtonClass}
            >
              <span aria-hidden="true">{docked ? "▣" : "▢"}</span>
            </button>
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
        {/* `closeTrayDrawer` only while undocked -- see this component's
            own docstring above for why a docked tray never passes it. */}
        <TrayPanel current={current} onAddToTray={handleAddToTray} closeTrayDrawer={docked ? undefined : close} />
      </div>
    </>
  );
}

/** Compat wrapper -- every call site that doesn't need the button/panel
 * split separately (Designer's own test harnesses, the integration test
 * inside PrintPreviewDeck.test.tsx) keeps rendering this unchanged.
 * AppShell.tsx itself mounts `GlobalTrayButton`/`GlobalTrayPanel`
 * separately instead, in different subtrees (header vs. dock rail). */
export function GlobalTrayDrawer() {
  return (
    <>
      <GlobalTrayButton />
      <GlobalTrayPanel />
    </>
  );
}
