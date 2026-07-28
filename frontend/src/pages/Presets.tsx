import { useEffect, useState } from "react";
import { PresetCard } from "../components/PresetCard";
import { Pending } from "../components/ui/Pending";
import { Select, TextInput } from "../components/ui/inputs";
import { errorText, fieldLabelText, panel, typeHeading } from "../components/ui/styles";
import { useLabelTypes } from "../hooks/useLabelTypes";
import { usePresets } from "../hooks/usePresets";

const SEARCH_DEBOUNCE_MS = 300;

/** The Presets page (task 2.13): search + type filter driving GET
 * /api/presets straight through as query params, a card grid, and the
 * empty state per the brief's own copy voice ("No presets yet. Design a
 * label and choose Save as preset to reuse it."). Saving a NEW preset
 * happens from the Designer (components/SavePresetDialog.tsx, "near the
 * tray") -- this page only lists/manages ones that already exist. */
export function Presets() {
  const { data: labelTypes } = useLabelTypes();
  const [rawQuery, setRawQuery] = useState("");
  const [q, setQ] = useState("");
  const [labelType, setLabelType] = useState("");

  useEffect(() => {
    const handle = setTimeout(() => setQ(rawQuery), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [rawQuery]);

  const { data: presets, isPending, isError } = usePresets({ labelType: labelType || undefined, q: q || undefined });

  const typeOptions = [{ value: "", label: "All types" }, ...(labelTypes ?? []).map((t) => ({ value: t.type, label: t.title }))];
  const typeTitleByType = new Map((labelTypes ?? []).map((t) => [t.type, t.title]));
  const isFiltered = q !== "" || labelType !== "";

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <h1 className={typeHeading}>Presets</h1>

      <div className={panel}>
        <div className="mb-5 flex flex-wrap items-end gap-3">
          <div className="min-w-[200px] flex-1">
            <label htmlFor="preset-search" className={`${fieldLabelText} mb-1 block`}>
              Search
            </label>
            <TextInput id="preset-search" value={rawQuery} onChange={setRawQuery} placeholder="Search presets by name…" />
          </div>
          <div>
            <label htmlFor="preset-type-filter" className={`${fieldLabelText} mb-1 block`}>
              Type
            </label>
            <Select id="preset-type-filter" value={labelType} onChange={setLabelType} options={typeOptions} />
          </div>
        </div>

        {isPending ? (
          <Pending />
        ) : isError ? (
          <p role="alert" className={errorText}>
            Could not load presets.
          </p>
        ) : presets.length === 0 ? (
          <p className="text-[13px] text-deck-400">
            {isFiltered ? "No presets match this search." : "No presets yet. Design a label and choose Save as preset to reuse it."}
          </p>
        ) : (
          <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {presets.map((preset) => (
              <PresetCard key={preset.id} preset={preset} typeTitle={typeTitleByType.get(preset.label_type) ?? preset.label_type} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
