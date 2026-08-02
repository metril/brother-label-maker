import { useEffect, useMemo, useRef, useState } from "react";
import { symbolSvgUrl } from "../../api/client";
import { useSymbols } from "../../hooks/useSymbols";
import { SegmentedControl } from "../ui/SegmentedControl";
import { Pending } from "../ui/Pending";
import { TextInput } from "../ui/inputs";

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
 * see WINDOW_SIZE's own docstring. */
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

  const presentCategories = useMemo(() => {
    if (!symbols) return [] as CategoryValue[];
    const present = new Set(symbols.map((s) => s.category));
    return CATEGORY_ORDER.filter((c) => present.has(c));
  }, [symbols]);

  // A category switch or a new search term is a new "view" of the catalog,
  // not a continuation of wherever scrolling had grown the previous one to
  // -- start each one back at the initial window.
  useEffect(() => {
    setWindowCount(WINDOW_SIZE);
  }, [query, category]);

  // One IntersectionObserver for this browser's whole lifetime, not
  // recreated per render/filter change (jsdom has no real
  // IntersectionObserver -- see test/setup.ts's MockIntersectionObserver).
  // Built lazily during render (React's "lazy ref initialization" idiom),
  // NOT inside a useEffect: refs attach (running the grid's sentinel ref
  // callback below) during the commit phase, which happens before passive
  // effects run -- an effect-created observer would still be null the
  // first time the sentinel mounts, so the very first grid would never
  // get observed.
  if (observerRef.current === null) {
    observerRef.current = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        setWindowCount((c) => Math.min(c + WINDOW_SIZE, filteredLengthRef.current));
      }
    });
  }
  useEffect(() => () => observerRef.current?.disconnect(), []);

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

  function sentinelRef(el: HTMLDivElement | null) {
    if (el) observerRef.current?.observe(el);
  }

  if (isPending || !symbols) return <Pending />;

  const q = query.trim().toLowerCase();
  const filtered = symbols.filter((s) => {
    if (category !== "all" && s.category !== category) return false;
    if (!q) return true;
    return s.id.includes(q) || s.name.toLowerCase().includes(q) || s.tags.some((t) => t.includes(q));
  });
  filteredLengthRef.current = filtered.length;

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
    if (filtered.length === 0) return;
    const wrapped = (index + filtered.length) % filtered.length;
    const target = filtered[wrapped]!;
    if (wrapped >= windowCount) {
      // Walked past the rendered edge -- grow the window enough to cover
      // this index (rounded up to a WINDOW_SIZE boundary, the same
      // granularity the sentinel itself grows by) and focus it once it
      // renders (the pendingFocusId effect above does that the instant it
      // shows up).
      pendingFocusIdRef.current = target.id;
      setWindowCount(Math.min(filtered.length, Math.ceil((wrapped + 1) / WINDOW_SIZE) * WINDOW_SIZE));
      return;
    }
    buttonRefs.current.get(target.id)?.focus();
  }

  function handleKeyDown(event: React.KeyboardEvent, index: number) {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft" && event.key !== "ArrowDown" && event.key !== "ArrowUp") {
      return;
    }
    event.preventDefault();
    const forward = event.key === "ArrowRight" || event.key === "ArrowDown";
    focusByIndex(index + (forward ? 1 : -1));
  }

  const categoryOptions: { value: CategoryFilter; label: string }[] = [
    { value: "all", label: "All" },
    ...presentCategories.map((c) => ({ value: c, label: CATEGORY_LABELS[c] })),
  ];

  const selected = props.mode === "select" && props.selectedId ? (symbols.find((s) => s.id === props.selectedId) ?? null) : null;
  const detail = props.mode === "browse" && detailId ? (symbols.find((s) => s.id === detailId) ?? null) : null;

  return (
    <div className="flex flex-col gap-2">
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
      {detail && (
        // Browse mode's lightweight detail affordance -- opened by
        // clicking (or activating via keyboard) an icon in the grid below,
        // closed by clicking it again or this panel's own "Close" button.
        // Stays visible above the grid regardless of the active filter,
        // same rationale as the selected chip above.
        <div role="group" aria-label={`${detail.name} details`} className="flex items-start gap-3 rounded-md border border-deck-700 bg-icon-well/60 p-3">
          <img src={symbolSvgUrl(detail.id)} alt="" loading="lazy" className="h-12 w-12 shrink-0" />
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <div className="flex items-start justify-between gap-2">
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
      <div role="listbox" aria-label="Symbol" className="grid max-h-56 grid-cols-6 gap-1.5 overflow-y-auto rounded-md border border-deck-700 bg-deck-900/40 p-2 sm:grid-cols-8">
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
              aria-selected={marked}
              tabIndex={symbol.id === activeId ? 0 : -1}
              title={symbol.name}
              onClick={() => activate(symbol.id)}
              onKeyDown={(e) => handleKeyDown(e, index)}
              // content-visibility/contain-intrinsic-size have no Tailwind
              // v4 utility for an arbitrary two-axis size, so plain
              // `style` here -- same rationale as ui/inputs.tsx's Select
              // chevron. Skips layout/paint for grid items scrolled out of
              // the max-h-56 viewport (on top of windowing itself, which
              // caps how many of these exist in the DOM at all).
              style={{ contentVisibility: "auto", containIntrinsicSize: "36px 36px" }}
              className={`flex h-9 w-9 items-center justify-center rounded-md border p-1.5 ${
                marked ? "border-amber-500 bg-icon-well" : "border-deck-600 bg-icon-well/90 hover:bg-icon-well"
              }`}
            >
              <img src={symbolSvgUrl(symbol.id)} alt={symbol.name} loading="lazy" className="h-full w-full" />
            </button>
          );
        })}
        {windowCount < filtered.length && <div ref={sentinelRef} aria-hidden="true" className="col-span-full h-px" />}
        {filtered.length === 0 && (
          <p className="col-span-full text-[12px] text-deck-400">
            No symbols match{q ? ` "${query}"` : ""}
            {category !== "all" ? ` in ${CATEGORY_LABELS[category]}` : ""}.
          </p>
        )}
      </div>
    </div>
  );
}
