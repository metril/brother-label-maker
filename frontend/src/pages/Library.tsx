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
 * account for that separately. */
export function Library() {
  const [tab, setTab] = useState<LibraryTab>("symbols");

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <h1 className={typeHeading}>Library</h1>

      <SegmentedControl ariaLabel="Library section" options={TAB_OPTIONS} value={tab} onChange={setTab} />

      {tab === "symbols" ? (
        <div className={panel}>
          <p className="mb-5 text-[13px] text-deck-400">
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
  );
}
