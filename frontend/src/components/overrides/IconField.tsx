import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ApiError, imagePngUrl, postImage, symbolSvgUrl } from "../../api/client";
import type { Icon } from "../../api/types";
import { useSymbols } from "../../hooks/useSymbols";
import { SegmentedControl } from "../ui/SegmentedControl";
import { Pending } from "../ui/Pending";
import { NumberInput, TextInput } from "../ui/inputs";
import { errorText, fieldLabelText, helpText, segmentedButtonClass } from "../ui/styles";
import type { OverrideFieldProps } from "./types";

type IconMode = "none" | "symbol" | "image";

/** "text" type's `icon` field (task 2.7's leading-art discriminated union)
 * -- not schema-walked generically (a discriminator union is one shape too
 * bespoke to earn a generic renderer for a single field across one type),
 * a bespoke picker instead: symbol grid (searchable by tag, from GET
 * /api/symbols) or image upload (POST /api/images) with a thumbnail and a
 * clear affordance, per the task brief. */
export function IconField({ value, onChange }: OverrideFieldProps) {
  const icon = (value ?? null) as Icon | null;
  // While `icon` is null, which picker to SHOW is UI-only state -- switching
  // to the "Symbol" or "Image" tab must never itself write a half-formed
  // Icon (e.g. `{kind: "symbol", id: ""}`) into params, since that's a
  // value the backend would 422 on if a preview/print fired before the user
  // actually picked something. Once `icon` is non-null, its own `.kind` is
  // authoritative (a real, valid value) and this local state stops mattering.
  const [pendingMode, setPendingMode] = useState<IconMode>("none");
  const mode: IconMode = icon ? icon.kind : pendingMode;

  function setMode(next: IconMode) {
    if (next === "none") onChange(null);
    setPendingMode(next);
  }

  return (
    <div className="flex flex-col gap-2">
      <span className={`${fieldLabelText} mb-1 block`}>Icon</span>
      <SegmentedControl
        ariaLabel="Icon mode"
        value={mode}
        options={[
          { value: "none", label: "None" },
          { value: "symbol", label: "Symbol" },
          { value: "image", label: "Image" },
        ]}
        onChange={setMode}
      />
      <p className={helpText}>
        Optional leading art at the left of the text, sized to the full print height.
      </p>
      {mode === "symbol" && (
        <SymbolPicker
          selectedId={icon?.kind === "symbol" ? icon.id : null}
          onSelect={(id) => onChange({ kind: "symbol", id } satisfies Icon)}
          onClear={() => onChange(null)}
        />
      )}
      {mode === "image" && (
        <ImagePicker
          icon={icon?.kind === "image" ? icon : null}
          onChange={(next) => onChange(next)}
          onClear={() => onChange(null)}
        />
      )}
    </div>
  );
}

/** Rendered slice size for the windowed grid below -- initial render, and
 * each subsequent grow step (sentinel scroll, or keyboard nav past the
 * rendered edge), both move `windowCount` by this many items. */
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

interface SymbolPickerProps {
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** Clears the icon back to `null` -- the selected chip's own affordance
   * for deselecting without leaving the "Symbol" tab (parallels
   * ImagePicker's "Clear image" button below). */
  onClear: () => void;
}

function SymbolPicker({ selectedId, onSelect, onClear }: SymbolPickerProps) {
  const { data: symbols, isPending } = useSymbols();
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<CategoryFilter>("all");
  const [windowCount, setWindowCount] = useState(WINDOW_SIZE);
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

  // One IntersectionObserver for this picker's whole lifetime, not
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

  // Windowed rendering (commit 8: the catalog grew from 60 to 858 icons) --
  // the DOM only ever holds up to `windowCount` grid items (initially
  // WINDOW_SIZE, grown by WINDOW_SIZE at a time), never the full filtered
  // list, so scrolling "All" never fires hundreds of eager symbol-SVG
  // requests up front. `visible` is what's actually rendered; `filtered`
  // (the complete matching set) is still what the count line and keyboard
  // wraparound below reason about. The sentinel div at the end of the grid
  // grows the window via IntersectionObserver when it scrolls into view;
  // focusByIndex grows it directly when arrow-key nav walks past the
  // rendered edge (see its own comment).
  const visible = filtered.slice(0, windowCount);

  // Roving tabindex (ARIA listbox authoring practice): only ONE option is
  // ever a tab stop -- the selected one (if currently rendered), or the
  // first rendered result otherwise -- not every option (a keyboard user
  // tabbing through the form would otherwise have to step through every
  // rendered icon one at a time to get past this field). Computed from
  // `visible`, not `filtered`: a selection outside the current window has
  // no DOM node to focus onto yet -- its own chip below stands in for it
  // visually (see `selected`).
  const activeId = (selectedId && visible.some((s) => s.id === selectedId) ? selectedId : visible[0]?.id) ?? null;

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

  const selected = selectedId ? (symbols.find((s) => s.id === selectedId) ?? null) : null;

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
          <button type="button" onClick={onClear} className="shrink-0 text-[12px] text-deck-400 underline hover:text-deck-200">
            Clear
          </button>
        </div>
      )}
      <div role="listbox" aria-label="Symbol" className="grid max-h-56 grid-cols-6 gap-1.5 overflow-y-auto rounded-md border border-deck-700 bg-deck-900/40 p-2 sm:grid-cols-8">
        {visible.map((symbol, index) => (
          <button
            key={symbol.id}
            ref={(el) => {
              if (el) buttonRefs.current.set(symbol.id, el);
              else buttonRefs.current.delete(symbol.id);
            }}
            type="button"
            role="option"
            aria-selected={selectedId === symbol.id}
            tabIndex={symbol.id === activeId ? 0 : -1}
            title={symbol.name}
            onClick={() => onSelect(symbol.id)}
            onKeyDown={(e) => handleKeyDown(e, index)}
            // content-visibility/contain-intrinsic-size have no Tailwind v4
            // utility for an arbitrary two-axis size, so plain `style` here
            // -- same rationale as ui/inputs.tsx's Select chevron. Skips
            // layout/paint for grid items scrolled out of the max-h-56
            // viewport (on top of windowing itself, which caps how many of
            // these exist in the DOM at all).
            style={{ contentVisibility: "auto", containIntrinsicSize: "36px 36px" }}
            className={`flex h-9 w-9 items-center justify-center rounded-md border p-1.5 ${
              selectedId === symbol.id ? "border-amber-500 bg-icon-well" : "border-deck-600 bg-icon-well/90 hover:bg-icon-well"
            }`}
          >
            <img src={symbolSvgUrl(symbol.id)} alt={symbol.name} loading="lazy" className="h-full w-full" />
          </button>
        ))}
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

interface ImagePickerProps {
  icon: Extract<Icon, { kind: "image" }> | null;
  onChange: (icon: Icon) => void;
  onClear: () => void;
}

function ImagePicker({ icon, onChange, onClear }: ImagePickerProps) {
  const upload = useMutation({
    mutationFn: postImage,
    onSuccess: (result) => onChange({ kind: "image", image_id: result.image_id, mode: "threshold", threshold: 128 }),
  });

  if (!icon) {
    return (
      <div className="flex flex-col gap-1.5">
        <input
          type="file"
          accept="image/png,image/jpeg,image/webp"
          aria-label="Upload image"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) upload.mutate(file);
            e.target.value = "";
          }}
          className="text-[12px] text-deck-400 file:mr-3 file:rounded-md file:border file:border-deck-600 file:bg-deck-800 file:px-3 file:py-1.5 file:text-deck-200"
        />
        {upload.isPending && <Pending />}
        {upload.isError && (
          <p role="alert" className={errorText}>
            {upload.error instanceof ApiError ? upload.error.message : "image upload failed"}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="flex items-start gap-3">
      <img
        src={imagePngUrl(icon.image_id)}
        alt="Uploaded icon"
        className="h-16 w-16 shrink-0 rounded-md border border-deck-600 bg-icon-well object-contain p-1"
      />
      <div className="flex flex-1 flex-col gap-2">
        <div role="radiogroup" aria-label="Image mode" className="flex gap-1.5">
          {(["threshold", "dither"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={icon.mode === m}
              onClick={() => onChange({ ...icon, mode: m })}
              className={segmentedButtonClass(icon.mode === m)}
            >
              {m === "threshold" ? "Threshold" : "Dither"}
            </button>
          ))}
        </div>
        {icon.mode === "threshold" && (
          <label className="flex items-center gap-2 text-[12px] text-deck-400">
            Threshold
            <NumberInput
              value={icon.threshold}
              min={0}
              max={255}
              step={1}
              ariaLabel="Threshold"
              // A cleared/invalid threshold has no top-level schema-driven
              // safety net (icon's discriminated union is opaque to
              // hasNumberOutOfRange, see numberValidity.ts's own docstring)
              // -- no-op instead of ever writing a NaN-ish threshold into
              // params; the field's own local text buffer (NumberInput)
              // still shows whatever the user is mid-typing.
              onChange={(v) => {
                if (v === undefined) return;
                onChange({ ...icon, threshold: Math.round(v) });
              }}
              className="w-20 rounded-md border border-deck-600 bg-deck-800 px-2 py-1 font-mono text-[13px] text-deck-200"
            />
          </label>
        )}
        <button type="button" onClick={onClear} className="self-start text-[12px] text-deck-400 underline hover:text-deck-200">
          Clear image
        </button>
      </div>
    </div>
  );
}
