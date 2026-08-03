import { useState } from "react";
import { SymbolBrowser } from "../components/symbols/SymbolBrowser";
import { UploadsGallery } from "../components/library/UploadsGallery";
import { SegmentedControl } from "../components/ui/SegmentedControl";
import { panel, typeHeading } from "../components/ui/styles";

type LibraryTab = "symbols" | "uploads";

const TAB_OPTIONS: { value: LibraryTab; label: string }[] = [
  { value: "symbols", label: "Symbols" },
  { value: "uploads", label: "Uploads" },
];

/** The Library page: one place to browse everything the designer's icon
 * field can draw art from -- the committed symbol catalog (components/
 * symbols/SymbolBrowser.tsx in "browse" mode, the same windowed/searchable
 * grid IconField.tsx uses in "select" mode, minus the selection chip) and
 * every previously uploaded logo/photo (components/library/UploadsGallery.tsx,
 * fully self-contained -- owns its own list query, upload mutation, and
 * delete confirm flow). Both pieces already existed for IconField's own
 * picker/uploader; this page is just a second, browse-only home for them.
 *
 * Local `tab` state only, not synced to a URL search param -- no other page
 * in the app uses useSearchParams (grep confirms it), so there's no existing
 * convention to lean on, and a page this shallow doesn't earn inventing one.
 * SymbolBrowser's own windowing keeps the "Symbols" tab catalog-size-proof
 * as the committed catalog grows toward ~8k icons -- nothing here needs to
 * account for that separately.
 *
 * Full-bleed, viewport-filling layout (2026-08 rework, replacing the old
 * `mx-auto max-w-6xl` centered panel -- user feedback: a whole route for
 * "browse the catalog" wasted most of its width on margins and capped the
 * grid at a popover-sized `max-h-56` scrollbox). AppShell's `<main>` (which
 * this page can't edit) is `flex-1 overflow-y-auto p-4 sm:p-6` inside a
 * `min-h-screen` chain with no `min-h-0` anywhere above it -- by itself
 * that lets content grow the whole page taller than the viewport rather
 * than ever triggering `<main>`'s own internal scrollbar (the classic
 * flexbox "min-height: auto" trap). This page routes around that by giving
 * its OWN root an explicit height instead of relying on flex-grow through
 * that unbounded chain: `h-[calc(100vh-6.5rem)]` reserves space for
 * AppShell's header (measured 52.5px tall at desktop widths, single row)
 * plus `<main>`'s own `sm:p-6` vertical padding (48px) -- ~100.5px, rounded
 * up. Below `sm` the header can wrap to 2-3 rows (measured up to ~135px at
 * 640px-ish widths) and this budget undershoots; the page then simply falls
 * back to the pre-rework behavior of a few extra px of ordinary page
 * scroll, which is harmless on the narrow/touch viewports where that
 * happens. `min-h-[26rem]` is the floor for very short viewports (e.g.
 * landscape phones), where the calc alone could otherwise collapse the
 * grid toward zero height.
 *
 * Inside that fixed-height box: header row + tab switcher stay their
 * natural size, and the active tab's content (`min-h-0 flex-1`) claims
 * everything left over, with SymbolBrowser/UploadsGallery each owning
 * their own internal scroll region rather than a small fixed max-height
 * box. */
export function Library() {
  const [tab, setTab] = useState<LibraryTab>("symbols");

  return (
    <div className="flex h-[calc(100vh-6.5rem)] min-h-[26rem] w-full flex-col gap-4">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3">
        <h1 className={typeHeading}>Library</h1>
        <SegmentedControl ariaLabel="Library section" options={TAB_OPTIONS} value={tab} onChange={setTab} />
      </div>

      <div className="min-h-0 flex-1">
        {tab === "symbols" ? (
          <div className={`${panel} flex h-full min-h-0 flex-col`}>
            <p className="mb-4 shrink-0 text-[13px] text-deck-400">
              Every symbol the designer's icon field can draw on — search or browse by category.
            </p>
            <SymbolBrowser mode="browse" />
          </div>
        ) : (
          // UploadsGallery renders its own panel -- no extra wrapper here,
          // same convention as embedding any other self-contained section.
          <UploadsGallery />
        )}
      </div>
    </div>
  );
}
