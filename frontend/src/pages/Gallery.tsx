import { useNavigate } from "react-router-dom";
import { pngDataUrl } from "../api/client";
import { DeckStrip, WarningChipRow } from "../components/FeedDeck";
import { Pending } from "../components/ui/Pending";
import { errorText, panel, typeHeading } from "../components/ui/styles";
import { useGallery } from "../hooks/useGallery";
import { useLabelTypes } from "../hooks/useLabelTypes";
import { useTapes } from "../hooks/useTapes";
import { humanizeEnumValue } from "../schema/humanize";
import { useDesignerStore } from "../stores/designer";
import type { GalleryItem, TapeInfo } from "../api/types";

/** The Gallery page (task 2.14): every label type as a curated, really-
 * rendered example -- the visual-QA artifact for the whole catalogue. Each
 * card's PNG comes from GET /api/gallery, which renders through the exact
 * /api/render/preview pipeline server-side, so what a card shows is what
 * the designer (and the printer) would produce for the same definition.
 * Deliberately minimal per the brief: no filters, no pagination, no
 * interactivity beyond "Open in designer". */
export function Gallery() {
  const { data: items, isPending, isError } = useGallery();
  const { data: tapes } = useTapes();

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <h1 className={typeHeading}>Gallery</h1>

      <div className={panel}>
        <p className="mb-5 text-[13px] text-deck-400">
          One real render per label type — exactly what the printer would produce. Open any example
          in the designer to make it yours.
        </p>

        {isPending ? (
          <Pending />
        ) : isError ? (
          <p role="alert" className={errorText}>
            Could not load the gallery.
          </p>
        ) : items.length === 0 ? (
          <p className="text-[13px] text-deck-400">The gallery is empty.</p>
        ) : (
          <ul className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {items.map((item) => (
              <GalleryCard key={item.id} item={item} tapes={tapes} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function GalleryCard({ item, tapes }: { item: GalleryItem; tapes: TapeInfo[] | undefined }) {
  const navigate = useNavigate();
  const { data: labelTypes } = useLabelTypes();

  const selectType = useDesignerStore((s) => s.selectType);
  const setParams = useDesignerStore((s) => s.setParams);
  const setTapeWidthMm = useDesignerStore((s) => s.setTapeWidthMm);
  const setTapeFamily = useDesignerStore((s) => s.setTapeFamily);

  // Same guarded-lookup convention as PresetCard's handleLoad: the whole
  // action (and the button) is gated on the type actually existing in the
  // catalog, so params are never written under a type that was never
  // selected.
  const typeInfo = labelTypes?.find((t) => t.type === item.type);
  const tapeInfo = tapes?.find((t) => t.nominal_mm === item.tape.width_mm && t.family === item.tape.family);

  function handleOpen() {
    if (!typeInfo) return;
    selectType(item.type, typeInfo.params_schema);
    setParams(item.type, item.params);
    setTapeFamily(item.tape.family);
    setTapeWidthMm(item.tape.width_mm);
    navigate("/");
  }

  const warningList = item.warnings.filter((w) => w.severity === "warning");
  const infoList = item.warnings.filter((w) => w.severity === "info");

  return (
    <li className="flex flex-col gap-3 rounded-xl border border-deck-800 bg-deck-900/60 p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="font-condensed text-[16px] font-semibold text-deck-200">{item.title}</h3>
          <p className="mt-0.5 text-[12px] leading-snug text-deck-400">{item.blurb}</p>
        </div>
        <button
          type="button"
          onClick={handleOpen}
          disabled={!typeInfo}
          title={typeInfo ? undefined : "This label type isn't available"}
          className="shrink-0 text-[12px] font-medium text-amber-300 hover:underline disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:no-underline"
        >
          Open in designer
        </button>
      </div>

      {/* Long labels (a 200mm punch-down strip) scroll inside the card
          rather than blowing the grid open. */}
      <div className="overflow-x-auto py-1">
        {tapeInfo ? (
          <DeckStrip
            png={pngDataUrl(item.png_b64)}
            lengthMm={item.length_mm}
            nominalMm={item.tape.width_mm}
            printMm={tapeInfo.print_mm}
            minFeedMm={item.min_feed_mm}
            isFetching={false}
          />
        ) : (
          <Pending />
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] text-deck-400">
        <span className="rounded border border-deck-600 px-1.5 py-0.5 font-condensed text-[10px] uppercase tracking-wide">
          {typeInfo?.title ?? item.type}
        </span>
        <span>
          {item.tape.width_mm}mm {humanizeEnumValue(item.tape.family)}
        </span>
        <span>{item.length_mm.toFixed(1)} mm</span>
        {item.total_labels != null && <span>label 1 of {item.total_labels}</span>}
      </div>

      {(warningList.length > 0 || infoList.length > 0) && (
        <div className="flex flex-col gap-1.5">
          {warningList.length > 0 && <WarningChipRow warnings={warningList} tone="warning" />}
          {infoList.length > 0 && <WarningChipRow warnings={infoList} tone="info" />}
        </div>
      )}
    </li>
  );
}
