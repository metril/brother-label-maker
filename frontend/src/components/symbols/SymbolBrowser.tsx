import { useEffect, useMemo, useRef, useState } from "react";
import { symbolSvgUrl } from "../../api/client";
import { useSymbols } from "../../hooks/useSymbols";
import { columnCount } from "../../lib/columnCount";
import { SegmentedControl } from "../ui/SegmentedControl";
import { Pending } from "../ui/Pending";
import { TextInput } from "../ui/inputs";
import type { SymbolInfo } from "../../api/types";

/** Rendered slice size for the windowed grid below -- initial render, and
 * each subsequent grow step (sentinel scroll, or keyboard nav past the
 * rendered edge), both move `windowCount` by this many items. Sized for
 * the current ~858-icon catalog and kept identical regardless of how much
 * bigger the catalog gets (the pipeline's next drop is ~8k icons) -- the
 * windowing scheme, not this constant, is what makes the grid catalog-
 * size-proof. */
const WINDOW_SIZE = 96;

/** Manifest v2's fixed category vocabulary (see SymbolInfo's own docstring
 * in api/types.ts) in display order -- "safety" is reserved for a future
 * source and currently unpopulated, so it only shows up as a tab once some
 * symbol actually carries it (see `presentCategories` below); nothing here
 * hardcodes an assumption that every value is present. */
const CATEGORY_ORDER = ["general", "electrical", "network", "av", "arrow", "misc", "safety"] as const;
type CategoryValue = (typeof CATEGORY_ORDER)[number];
type CategoryFilter = "all" | CategoryValue;

const CATEGORY_LABELS: Record<CategoryValue, string> = {
  general: "General",
  electrical: "Electrical",
  network: "Network",
  av: "AV",
  arrow: "Arrow",
  misc: "Misc",
  safety: "Safety",
};

/** Falls back to the raw category string for a (currently impossible per
 * SymbolInfo's docstring, but not type-guaranteed) value outside
 * CATEGORY_ORDER, rather than rendering `undefined`. */
function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category as CategoryValue] ?? category;
}

interface SymbolBrowserSelectProps {
  mode: "select";
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** Clears the icon back to `null` -- the selected chip's own affordance
   * for deselecting without leaving the grid (parallels ImagePicker's
   * "Clear image" button in IconField.tsx). */
  onClear: () => void;
}

interface SymbolBrowserBrowseProps {
  mode: "browse";
}

/** Two modes over the same searchable/windowed catalog grid:
 * - `select`: IconField.tsx's symbol picker -- clicking an icon reports it
 *   via `onSelect`, and a chip above the grid shows the current
 *   `selectedId` (with its own `onClear`) even when the active filter
 *   would otherwise hide it from the grid. Exactly today's SymbolPicker
 *   behavior.
 * - `browse`: no selection semantics -- clicking an icon instead opens a
 *   lightweight inline detail panel (name/id/category/tags/source/
 *   license) above the grid; clicking the same icon again closes it. For
 *   a future Library-style page that just wants to look through the
 *   catalog.
 *
 * Grid sizing/windowing (WINDOW_SIZE, the IntersectionObserver sentinel,
 * arrow-key growth) is identical in both modes and catalog-size-proof --
 * see WINDOW_SIZE's own docstring. Grid DENSITY/tile size and the detail
 * panel's layout are NOT identical (2026-08 Library page rework): `select`
 * mode is IconField's icon-field popover and must stay pixel-for-pixel
 * what it always was (same `max-h-56`/`grid-cols-6 sm:grid-cols-8`/`h-9
 * w-9` tiles, no visible per-tile label, and its `role="listbox"` div's own
 * className is never touched by anything keyed off `browse`) -- every
 * className/style branch below keyed on `props.mode === "select"`
 * reproduces that exact markup unchanged. `browse` mode (pages/Library.tsx's
 * whole-viewport tab) instead gets a denser auto-fill grid of bigger,
 * labeled tiles that grows to fill its host's height, and (see the detail
 * panel below) reflows into a right-hand sidebar at `xl`. */
export type SymbolBrowserProps = SymbolBrowserSelectProps | SymbolBrowserBrowseProps;

export function SymbolBrowser(props: SymbolBrowserProps) {
  const { data: symbols, isPending } = useSymbols();
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<CategoryFilter>("all");
  const [windowCount, setWindowCount] = useState(WINDOW_SIZE);
  // Browse mode's open detail panel -- unused (and never set) in select
  // mode, which uses `selectedId`/`onSelect` from props instead.
  const [detailId, setDetailId] = useState<string | null>(null);
  const buttonRefs = useRef(new Map<string, HTMLButtonElement>());
  const pendingFocusIdRef = useRef<string | null>(null);
  const observerRef = useRef<IntersectionObserver | null>(null);
  // Updated fresh every render (see below) so the long-lived observer
  // callback below never closes over a stale filtered-list length.
  const filteredLengthRef = useRef(0);
  // The grid's own scroll container (the `role="listbox"` div) and its
  // trailing sentinel -- both wired up below via ref callbacks rather than
  // queried through the DOM, so this keeps working identically under
  // jsdom's MockIntersectionObserver. `observedSentinelRef` is whichever
  // element the observer is CURRENTLY observing, so a mount/unmount can
  // `unobserve` the right one even after `sentinelElRef` has already moved
  // on to a new (or no) node.
  const gridElRef = useRef<HTMLDivElement | null>(null);
  const sentinelElRef = useRef<HTMLDivElement | null>(null);
  const observedSentinelRef = useRef<Element | null>(null);

  const presentCategories = useMemo(() => {
    if (!symbols) return [] as CategoryValue[];
    const present = new Set(symbols.map((s) => s.category));
    return CATEGORY_ORDER.filter((c) => present.has(c));
  }, [symbols]);

  // L11 (docs/code-review-2026-08.md): re-filtering the whole catalog (8362
  // entries and growing) sat directly in the render body with no memo, so
  // it re-scanned on EVERY render -- not just when `query`/`category`
  // actually changed, but also on every windowCount grow from the sentinel
  // or keyboard nav below, and on any parent re-render. Memoized on the
  // only three things that actually change what it returns.
  const filtered = useMemo(() => {
    if (!symbols) return [];
    const q = query.trim().toLowerCase();
    return symbols.filter((s) => {
      if (category !== "all" && s.category !== category) return false;
      if (!q) return true;
      return s.id.includes(q) || s.name.toLowerCase().includes(q) || s.tags.some((t) => t.includes(q));
    });
  }, [symbols, query, category]);

  // L11's other half: the selected-chip/detail-panel lookups below used to
  // be an uncached `symbols.find(...)` -- cheaper per call than the filter
  // above, but on the same "runs every render" cadence whenever something
  // is selected/open.
  const symbolById = useMemo(() => {
    const map = new Map<string, SymbolInfo>();
    if (symbols) for (const s of symbols) map.set(s.id, s);
    return map;
  }, [symbols]);

  // A category switch or a new search term is a new "view" of the catalog,
  // not a continuation of wherever scrolling had grown the previous one to
  // -- start each one back at the initial window.
  useEffect(() => {
    setWindowCount(WINDOW_SIZE);
  }, [query, category]);

  // Bug fix (2026-08 Library rework, "windowing stalls after one grow"):
  // two independent defects, both addressed by `wireObserver` plus the
  // effect right below it.
  //
  // (a) the observer used to be constructed with NO `root` option, so it
  // measured intersection against the VIEWPORT -- wrong once the grid
  // became its own `overflow-y-auto` scroll region (true of both modes:
  // browse's whole-viewport Library tab and select's popover-sized box).
  // `root` is read-only for the observer's whole lifetime, so it has to be
  // set at CONSTRUCTION time from a real DOM node -- which doesn't exist
  // yet during render, hence construction is deferred to here (a ref
  // callback) rather than the old "lazy on first render" trick (fine when
  // root was always null, wrong now that it needs to be the grid).
  //
  // (b) the old `sentinelRef` only ever called `observe()`, never
  // `unobserve()` -- and `observe()` on a target the SAME observer is
  // already observing is a silent no-op (per spec), so once the sentinel
  // had fired once, re-observing the identical (still-mounted, still-
  // visible) DOM node the grid keeps reusing across a window grow never
  // fired again. `wireObserver` always unobserves-then-observes the
  // CURRENT sentinel, so every call re-arms it for a fresh evaluation of
  // whatever its intersection state is RIGHT NOW.
  //
  // `gridRef`/`sentinelRef` below both call this on every ref-callback
  // invocation (mount, unmount, and -- since neither is memoized -- every
  // re-render, same as this file's other inline refs), and whichever of
  // the grid/sentinel elements attaches SECOND is what actually completes
  // the wiring, so this is correct regardless of which one React happens
  // to attach first.
  function wireObserver() {
    if (observerRef.current === null && gridElRef.current) {
      observerRef.current = new IntersectionObserver(
        (entries) => {
          if (entries.some((entry) => entry.isIntersecting)) {
            setWindowCount((c) => Math.min(c + WINDOW_SIZE, filteredLengthRef.current));
          }
        },
        // rootMargin starts growing the window slightly BEFORE the
        // sentinel is actually on-screen, so a fast scroll never outruns
        // the grid's own render.
        { root: gridElRef.current, rootMargin: "400px" },
      );
    }
    const observer = observerRef.current;
    if (!observer) return;
    const current = sentinelElRef.current;
    if (observedSentinelRef.current && observedSentinelRef.current !== current) {
      observer.unobserve(observedSentinelRef.current);
      observedSentinelRef.current = null;
    }
    if (current) {
      observer.unobserve(current);
      observer.observe(current);
      observedSentinelRef.current = current;
    }
  }

  useEffect(() => () => observerRef.current?.disconnect(), []);

  // Explicit re-arm on every window GROW specifically (on top of the
  // general ref-callback churn above): the sentinel div is the SAME DOM
  // node before and after a grow (only its position among the grid's
  // children moves -- see the grid's own render below), so without this a
  // sentinel that's STILL visible right after growing (a short grid, or a
  // fast continuous scroll) would only ever grow the window by one
  // WINDOW_SIZE step in total.
  useEffect(() => {
    wireObserver();
    // wireObserver closes over refs only -- no reactive value besides
    // windowCount itself, which is the intentional trigger.
  }, [windowCount]);

  function gridRef(el: HTMLDivElement | null) {
    gridElRef.current = el;
    wireObserver();
  }

  function sentinelRef(el: HTMLDivElement | null) {
    sentinelElRef.current = el;
    wireObserver();
  }

  // Arrow-key nav can ask to focus an option beyond the currently rendered
  // window (focusByIndex's "walked past the edge" branch below); that
  // option's <button> doesn't exist until the windowCount update below
  // re-renders the grid. Runs after every render and focuses it the
  // instant it shows up, then clears the pending id -- a no-op otherwise.
  useEffect(() => {
    const id = pendingFocusIdRef.current;
    if (!id) return;
    const el = buttonRefs.current.get(id);
    if (el) {
      el.focus();
      pendingFocusIdRef.current = null;
    }
  });

  if (isPending || !symbols) return <Pending />;

  const q = query.trim().toLowerCase();

  // Windowed rendering (commit 8: the catalog grew from 60 to 858 icons,
  // and it's headed to ~8k) -- the DOM only ever holds up to `windowCount`
  // grid items (initially WINDOW_SIZE, grown by WINDOW_SIZE at a time),
  // never the full filtered list, so scrolling "All" never fires hundreds
  // (soon thousands) of eager symbol-SVG requests up front. `visible` is
  // what's actually rendered; `filtered` (the complete matching set) is
  // still what the count line and keyboard wraparound below reason about.
  // The sentinel div at the end of the grid grows the window via
  // IntersectionObserver when it scrolls into view; focusByIndex grows it
  // directly when arrow-key nav walks past the rendered edge (see its own
  // comment).
  filteredLengthRef.current = filtered.length;
  const visible = filtered.slice(0, windowCount);

  // The id a click/keyboard-activate on an option should act on: reported
  // upward via onSelect in select mode, or opened as the detail panel in
  // browse mode.
  function activate(id: string) {
    if (props.mode === "select") {
      props.onSelect(id);
    } else {
      setDetailId((cur) => (cur === id ? null : id));
    }
  }

  // Roving tabindex (ARIA listbox authoring practice): only ONE option is
  // ever a tab stop -- the "marked" one (if currently rendered), or the
  // first rendered result otherwise -- not every option (a keyboard user
  // tabbing through the form would otherwise have to step through every
  // rendered icon one at a time to get past this field). "Marked" is
  // `selectedId` in select mode, or the open detail panel's id in browse
  // mode. Computed from `visible`, not `filtered`: a mark outside the
  // current window has no DOM node to focus onto yet.
  const markedId = props.mode === "select" ? props.selectedId : detailId;
  const activeId = (markedId && visible.some((s) => s.id === markedId) ? markedId : visible[0]?.id) ?? null;

  function focusByIndex(index: number) {
    // H7 (docs/code-review-2026-08.md): this used to wrap out-of-range
    // indices with `(index + filtered.length) % filtered.length`, so
    // ArrowUp/ArrowLeft on the FIRST rendered option resolved to
    // `filtered.length - 1` -- past the rendered edge, which the branch
    // below then grows the window to cover. With "All" active against the
    // full catalog that's the entire filtered list committed in one React
    // pass (8362 nodes against the real catalog, from a single keypress).
    // No wraparound: an index outside [0, filtered.length) is simply not a
    // valid target, the same way ArrowUp on the first option of a plain
    // HTML <select> does nothing rather than looping around to the last.
    // This also covers the old `filtered.length === 0` guard (index can
    // never satisfy `>= 0 && < 0`).
    if (index < 0 || index >= filtered.length) return;
    const target = filtered[index]!;
    if (index >= windowCount) {
      // Walked past the rendered edge -- grow the window enough to cover
      // this index (rounded up to a WINDOW_SIZE boundary, the same
      // granularity the sentinel itself grows by -- forward nav only ever
      // walks one option past the current edge at a time, so this can
      // only ever add ONE WINDOW_SIZE step) and focus it once it renders
      // (the pendingFocusId effect above does that the instant it shows
      // up).
      pendingFocusIdRef.current = target.id;
      setWindowCount(Math.min(filtered.length, Math.ceil((index + 1) / WINDOW_SIZE) * WINDOW_SIZE));
      return;
    }
    buttonRefs.current.get(target.id)?.focus();
  }

  function handleKeyDown(event: React.KeyboardEvent, index: number) {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft" && event.key !== "ArrowDown" && event.key !== "ArrowUp") {
      return;
    }
    event.preventDefault();
    if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      focusByIndex(index + (event.key === "ArrowRight" ? 1 : -1));
      return;
    }
    // L12(a): ArrowDown/ArrowUp used to move by +-1, identical to
    // ArrowRight/ArrowLeft, in what's visually a multi-column grid -- move
    // by the CURRENT column count instead (see columnCount's own doc for
    // why this still exercises the exact +-1 path under jsdom).
    const step = columnCount(gridElRef.current);
    focusByIndex(index + (event.key === "ArrowDown" ? step : -step));
  }

  const categoryOptions: { value: CategoryFilter; label: string }[] = [
    { value: "all", label: "All" },
    ...presentCategories.map((c) => ({ value: c, label: CATEGORY_LABELS[c] })),
  ];

  const selected = props.mode === "select" && props.selectedId ? (symbolById.get(props.selectedId) ?? null) : null;
  const detail = props.mode === "browse" && detailId ? (symbolById.get(detailId) ?? null) : null;
  const browse = props.mode === "browse";

  // L12(b): the empty-state message used to render INSIDE `role="listbox"`
  // -- a static paragraph a screen reader walking the listbox would
  // encounter where it expects only `option`s (the sentinel div right
  // above it is fine as-is: it's `aria-hidden`, so already outside the a11y
  // tree). Built once here and placed as a SIBLING of the listbox div in
  // both modes below, instead.
  const emptyState = filtered.length === 0 && (
    <p className="text-[12px] text-deck-400">
      No symbols match{q ? ` "${query}"` : ""}
      {category !== "all" ? ` in ${CATEGORY_LABELS[category]}` : ""}.
    </p>
  );

  // The grid itself: identical windowing/keyboard-nav wiring in both
  // modes, but browse mode swaps in a denser auto-fill layout with bigger,
  // labeled tiles and lets the grid grow to fill its host's height instead
  // of capping at select mode's popover-sized `max-h-56`. Built once (not
  // duplicated per mode) so the option list/sentinel below is one source
  // of truth -- only the wrapping listbox's own className, and each tile's
  // className/style/children, branch on `browse`.
  const listbox = (
    <div
      ref={gridRef}
      role="listbox"
      aria-label="Symbol"
      className={
        browse
          ? // content-start/auto-rows-min (bug fix, 2026-08 Library rework):
            // grid's own `align-content` default is `normal`, which behaves
            // as `stretch` -- with fewer rows than the container's height
            // (routine once a search/category filter narrows the results),
            // every row was inflating to fill the leftover space, stretching
            // tiles vertically. Pinning rows to their own content height and
            // packing them against the top fixes it without affecting a
            // FULL grid (enough rows to fill the container regardless).
            "grid min-h-0 flex-1 grid-cols-[repeat(auto-fill,minmax(4.5rem,1fr))] content-start auto-rows-min gap-2 overflow-y-auto rounded-md border border-deck-700 bg-deck-900/40 p-3"
          : "grid max-h-56 grid-cols-6 gap-1.5 overflow-y-auto rounded-md border border-deck-700 bg-deck-900/40 p-2 sm:grid-cols-8"
      }
    >
      {visible.map((symbol, index) => {
        const marked = props.mode === "select" ? props.selectedId === symbol.id : detailId === symbol.id;
        return (
          <button
            key={symbol.id}
            ref={(el) => {
              if (el) buttonRefs.current.set(symbol.id, el);
              else buttonRefs.current.delete(symbol.id);
            }}
            type="button"
            role="option"
            // L18 (docs/code-review-2026-08.md): the option's accessible
            // NAME (the symbol's display name, via the img's alt text in
            // browse mode's markup below) is not unique across the 8335-
            // icon catalog -- a test indexing the fixture positionally and
            // then looking the option up by name is one catalog regen away
            // from an ambiguous "found multiple elements" failure. `id` IS
            // guaranteed unique (the catalog's own primary key), so this is
            // the reliable handle for tests to grab a SPECIFIC option by.
            data-testid={`symbol-option-${symbol.id}`}
            aria-selected={marked}
            tabIndex={symbol.id === activeId ? 0 : -1}
            title={symbol.name}
            onClick={() => activate(symbol.id)}
            onKeyDown={(e) => handleKeyDown(e, index)}
            // content-visibility/contain-intrinsic-size have no Tailwind
            // v4 utility for an arbitrary two-axis size, so plain `style`
            // here -- same rationale as ui/inputs.tsx's Select chevron.
            // Skips layout/paint for grid items scrolled out of view (on
            // top of windowing itself, which caps how many of these exist
            // in the DOM at all). Browse mode's tiles are taller (an
            // aspect-square icon well plus a label line below it), so its
            // intrinsic size guess is bigger too.
            style={
              browse
                ? { contentVisibility: "auto", containIntrinsicSize: "72px 96px" }
                : { contentVisibility: "auto", containIntrinsicSize: "36px 36px" }
            }
            className={
              browse
                ? // Bug fix (contrast, 2026-08 Library rework): the tile
                  // used to put the label directly on the light icon-well
                  // surface in text color token deck-300 -- a token that was
                  // never actually declared (the palette stops at deck-200/
                  // deck-400), so Tailwind emitted no rule and the label
                  // inherited near-white text onto a near-white background,
                  // ~1.02:1 contrast. Restructured (UploadsGallery.tsx's own
                  // grid-tile pattern) so the button's own surface is a
                  // normal dark deck panel and only the ICON sits on the
                  // light icon-well square below -- the name label now
                  // lives on the dark surface as deck-400, readable in both
                  // themes (see the icon well + label markup below).
                  `flex flex-col gap-1.5 rounded-md border p-2 ${
                    marked ? "border-amber-500 bg-amber-500/10" : "border-deck-600 bg-deck-900/40 hover:border-deck-400"
                  }`
                : `flex h-9 w-9 items-center justify-center rounded-md border p-1.5 ${
                    marked ? "border-amber-500 bg-icon-well" : "border-deck-600 bg-icon-well/90 hover:bg-icon-well"
                  }`
            }
          >
            {browse ? (
              <>
                {/* The icon well: light background behind black-line
                    symbol art, same token/rationale as the detail panel's
                    own icon swatch below and UploadsGallery's thumbnail
                    tile -- `object-contain` (missing before, added
                    defensively) keeps a non-square source SVG from
                    stretching to fill the square well. */}
                <span className="flex aspect-square w-full items-center justify-center overflow-hidden rounded-md border border-deck-600 bg-icon-well p-1.5">
                  <img src={symbolSvgUrl(symbol.id)} alt="" loading="lazy" className="h-full w-full object-contain" />
                </span>
                {/* The name is this real, visible <span> -- the image
                    itself is decorative here (empty alt): an
                    `alt={symbol.name}` on the image AND this label would
                    double up in the button's computed accessible name
                    (e.g. "Bolt Bolt"), breaking every `getByRole("option",
                    { name: ... })` lookup. */}
                <span className="w-full truncate text-center text-[11px] text-deck-400">{symbol.name}</span>
              </>
            ) : (
              // Select mode has no name span, so the img's own alt is
              // still the tile's only name source -- unchanged.
              <img src={symbolSvgUrl(symbol.id)} alt={symbol.name} loading="lazy" className="h-full w-full" />
            )}
          </button>
        );
      })}
      {windowCount < filtered.length && <div ref={sentinelRef} aria-hidden="true" className="col-span-full h-px" />}
    </div>
  );

  // Browse mode wraps the listbox + empty-state message in one flex-col
  // container so the pair stays a SINGLE flex item within the grid+detail
  // row below (see that row's own comment) -- otherwise, with 0 results,
  // the listbox (empty) and the message would become two separate row
  // items competing for space. Select mode has no such row to fit into
  // (its own root container is a plain top-to-bottom stack), so a bare
  // Fragment is enough there -- and leaves the listbox `<div>` above as its
  // own direct, unwrapped child, same as it always rendered.
  const grid = browse ? (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      {listbox}
      {emptyState}
    </div>
  ) : (
    <>
      {listbox}
      {emptyState}
    </>
  );

  return (
    <div className={browse ? "flex min-h-0 flex-1 flex-col gap-3" : "flex flex-col gap-2"}>
      <TextInput value={query} onChange={setQuery} placeholder='Search symbols (e.g. "network", "power")' ariaLabel="Search symbols" />
      <SegmentedControl ariaLabel="Symbol category" options={categoryOptions} value={category} onChange={setCategory} />
      <p className="text-[12px] text-deck-400">
        {filtered.length} symbol{filtered.length === 1 ? "" : "s"}
      </p>
      {selected && (
        // Shown above the grid regardless of the active filter/window --
        // clicking into "Network" or typing a search that excludes the
        // current selection must never make the selection itself vanish
        // from view.
        <div className="flex items-center gap-2 rounded-md border border-amber-500/60 bg-icon-well/60 px-2 py-1.5">
          <img src={symbolSvgUrl(selected.id)} alt="" loading="lazy" className="h-6 w-6 shrink-0" />
          <span className="flex-1 truncate text-[12px] text-deck-200">{selected.name}</span>
          <button type="button" onClick={props.mode === "select" ? props.onClear : undefined} className="shrink-0 text-[12px] text-deck-400 underline hover:text-deck-200">
            Clear
          </button>
        </div>
      )}
      {browse ? (
        // Grid + detail panel share ONE flex container so the panel can
        // reflow between two positions via plain responsive classes,
        // rather than rendering two copies of it (which would double up
        // `role="group"` nodes with the identical accessible name -- see
        // SymbolBrowser.test.tsx's own sidebar-layout test). Below `xl`:
        // `flex-col`, panel first -> renders above the grid, same spot
        // browse mode has always used. At `xl`+: `flex-row` plus
        // `xl:order-last` on the panel -> the grid takes the main column
        // and the panel becomes a persistent right-hand sidebar.
        <div className="flex min-h-0 flex-1 flex-col gap-3 xl:flex-row xl:gap-4">
          {detail && (
            // Browse mode's detail affordance -- opened by clicking (or
            // activating via keyboard) an icon in the grid, closed by
            // clicking it again or this panel's own "Close" button. Stays
            // visible regardless of the active filter, same rationale as
            // the selected chip above.
            <div
              role="group"
              aria-label={`${detail.name} details`}
              // Panel surface is a normal deck panel (readable deck-* text);
              // ONLY the icon sits on an icon-well tile, same as the grid's
              // own cells -- icon-well is a light token for icon contrast,
              // and body text on top of it is illegible in dark mode.
              className="flex shrink-0 items-start gap-3 rounded-md border border-deck-700 bg-deck-800 p-3 xl:order-last xl:w-72 xl:flex-col xl:items-center xl:gap-2 xl:p-4 xl:text-center"
            >
              <span className="shrink-0 rounded-md border border-deck-600 bg-icon-well p-1.5 xl:p-3">
                <img src={symbolSvgUrl(detail.id)} alt="" loading="lazy" className="block h-12 w-12 xl:h-24 xl:w-24" />
              </span>
              <div className="flex min-w-0 flex-1 flex-col gap-0.5 xl:w-full xl:items-center">
                <div className="flex w-full items-start justify-between gap-2">
                  <span className="truncate text-[13px] font-medium text-deck-200">{detail.name}</span>
                  <button type="button" onClick={() => setDetailId(null)} className="shrink-0 text-[12px] text-deck-400 underline hover:text-deck-200">
                    Close
                  </button>
                </div>
                <p className="truncate font-mono text-[11px] text-deck-400">{detail.id}</p>
                <p className="text-[11px] text-deck-400">{categoryLabel(detail.category)}</p>
                {detail.tags.length > 0 && <p className="truncate text-[11px] text-deck-400">{detail.tags.join(", ")}</p>}
                <p className="truncate text-[11px] text-deck-400">{`${detail.source} · ${detail.license}`}</p>
              </div>
            </div>
          )}
          {grid}
        </div>
      ) : (
        grid
      )}
    </div>
  );
}
