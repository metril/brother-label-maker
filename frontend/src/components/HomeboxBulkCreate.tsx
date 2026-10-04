import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ApiError, getHomeboxEntityPath, getHomeboxSettings, postExpand } from "../api/client";
import { useBulkCreateEntities, useHomeboxTags } from "../hooks/useHomeboxWrite";
import {
  buildBreadcrumb,
  buildHomeboxCableLabelDefinition,
  buildHomeboxLabelDefinition,
  describeHomeboxEntity,
  type HomeboxLabelKind,
} from "../lib/homebox";
import { DEFAULT_SEQUENCE, effectiveCount, validateSequence } from "../lib/sequence";
import { useDesignerStore } from "../stores/designer";
import { useTrayStore } from "../stores/tray";
import { useTrayDrawerStore } from "../stores/trayDrawer";
import { AlphaFields, ListValuesField, NumericFields } from "./SequenceEditor";
import { SegmentedControl } from "./ui/SegmentedControl";
import { Select, TextInput } from "./ui/inputs";
import { Switch } from "./ui/Switch";
import { checkboxClass, errorText, fieldLabelText, helpText, panel, panelHeading, primaryButtonClass } from "./ui/styles";
import type { HomeboxBulkRowResult, HomeboxEntitySummary, HomeboxPathSegment, Sequence, SequenceKind } from "../api/types";

const MAX_NAMES = 100;
const MAX_NAME_LEN = 255;
const SEQ_TOKEN = "{seq}";

// buildBreadcrumb drops the LAST path segment (the entity itself); a new
// item's breadcrumb is its parent's whole path, so append a placeholder.
const NEW_ITEM_SEGMENT: HomeboxPathSegment = { id: "", name: "", type: "item" };

const KIND_OPTIONS: { value: SequenceKind; label: string }[] = [
  { value: "numeric", label: "Numbers" },
  { value: "alpha", label: "Letters" },
  { value: "list", label: "List" },
];
const LABEL_TYPE_OPTIONS: { value: HomeboxLabelKind; label: string }[] = [
  { value: "cable_wrap", label: "Cable wrap" },
  { value: "cable_flag", label: "Cable flag" },
  { value: "homebox_asset", label: "HomeBox asset" },
];

function summaryFor(row: HomeboxBulkRowResult): HomeboxEntitySummary {
  const e = row.entity!;
  return {
    id: e.id,
    name: e.name,
    description: "",
    asset_id: e.asset_id,
    archived: false,
    quantity: null,
    entity_type: null,
    parent: null,
    tags: [],
    thumbnail_id: null,
    image_id: null,
  };
}

/** Bulk "create N items under a location, then print their labels" panel
 * (shown by pages/Homebox.tsx only when writes are enabled). The name
 * pattern's `{seq}` token is filled client-side from the distinct values
 * POST /api/render/expand returns for a LOCAL Sequence (the same expansion
 * the Designer's serializer uses -- SequenceEditor's field components are
 * reused, but its designer-store state is not shared). `parent` is the
 * page's selected location-tree node. */
export function HomeboxBulkCreate({ parent }: { parent: { id: string; name: string } | null }) {
  const tape = useDesignerStore((s) => s.tape);
  const addTrayItem = useTrayStore((s) => s.addItem);
  const openDrawer = useTrayDrawerStore((s) => s.openDrawer);
  const tags = useHomeboxTags();
  const bulk = useBulkCreateEntities();

  const [pattern, setPattern] = useState(`Cable ${SEQ_TOKEN}`);
  const [sequence, setSequence] = useState<Sequence>({ ...DEFAULT_SEQUENCE, count: 5 });
  const [tagIds, setTagIds] = useState<Set<string>>(new Set());
  const [labelKind, setLabelKind] = useState<HomeboxLabelKind>("cable_wrap");
  const [showQr, setShowQr] = useState(true);
  const [results, setResults] = useState<HomeboxBulkRowResult[] | null>(null);
  const [printError, setPrintError] = useState<string | null>(null);

  const fieldErrors = validateSequence(sequence);
  const expand = useQuery({
    queryKey: ["homebox-bulk-expand", JSON.stringify(sequence)],
    queryFn: () => postExpand({ serialization: sequence }),
    enabled: Object.keys(fieldErrors).length === 0,
    retry: false,
    staleTime: Infinity,
  });

  const values = expand.data?.values ?? [];
  const names = values.map((v) => pattern.split(SEQ_TOKEN).join(v).trim());
  const count = effectiveCount(sequence);

  let problem: string | null = null;
  if (!parent) problem = "Select a parent location in the tree first.";
  else if (Object.keys(fieldErrors).length > 0 || expand.isError) problem = "Fix the sequence settings above.";
  else if (names.length === 0) problem = expand.isPending ? null : "Nothing to create.";
  else if (names.length > MAX_NAMES) problem = `At most ${MAX_NAMES} items per batch.`;
  else if (names.some((n) => n === "" || n.length > MAX_NAME_LEN)) problem = `Each name must be 1-${MAX_NAME_LEN} characters.`;
  else if (names.length > 1 && !pattern.includes(SEQ_TOKEN)) problem = `Add ${SEQ_TOKEN} to the pattern so names differ.`;
  const canRun = problem === null && names.length > 0 && !bulk.isPending;

  function switchKind(kind: SequenceKind) {
    setSequence({ ...DEFAULT_SEQUENCE, kind, count: kind === "list" ? 1 : 5 });
  }

  function toggleTag(id: string) {
    setTagIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function run() {
    if (!parent) return;
    setPrintError(null);
    setResults(null);
    let response;
    try {
      response = await bulk.mutateAsync({ parent_id: parent.id, tag_ids: [...tagIds], names });
    } catch {
      return; // surfaced through bulk.error below
    }
    setResults(response.results);
    const created = response.results.filter((r) => r.ok && r.entity);
    if (created.length === 0) return;
    try {
      const settings = await getHomeboxSettings();
      const qrBase = showQr ? settings.effective_qr_base_url : null;
      const breadcrumb = labelKind === "homebox_asset" ? buildBreadcrumb([...(await getHomeboxEntityPath(parent.id)), NEW_ITEM_SEGMENT]) : "";
      for (const row of created) {
        const entity = summaryFor(row);
        const definition =
          labelKind === "homebox_asset"
            ? buildHomeboxLabelDefinition(entity, breadcrumb, qrBase, structuredClone(tape))
            : buildHomeboxCableLabelDefinition(entity, labelKind, qrBase, structuredClone(tape));
        addTrayItem({ definition, png: null, lengthMm: null, label: describeHomeboxEntity(entity) });
      }
      openDrawer();
    } catch (err) {
      setPrintError(err instanceof ApiError ? err.message : "Items were created, but their labels could not be added to the tray.");
    }
  }

  const okCount = results?.filter((r) => r.ok).length ?? 0;

  return (
    <section className={panel} aria-label="Bulk create">
      <h2 className={panelHeading}>Bulk create &amp; print</h2>
      <div className="flex flex-col gap-4">
        <p className="text-[13px] text-deck-400">
          Parent location: <span className="text-deck-200">{parent ? parent.name : "none selected (pick one in the tree)"}</span>
        </p>

        <div>
          <label htmlFor="bulk-pattern" className={fieldLabelText}>
            Name pattern
          </label>
          <TextInput id="bulk-pattern" value={pattern} onChange={setPattern} maxLength={MAX_NAME_LEN} />
          <p className={helpText}>
            <code className="font-mono">{SEQ_TOKEN}</code> is replaced by each value of the sequence below.
            {names.length > 0 && <> Preview: {names.slice(0, 3).join(", ")}{names.length > 3 ? ", …" : ""}</>}
          </p>
        </div>

        <div>
          <span className={`${fieldLabelText} mb-1.5`}>Sequence</span>
          <SegmentedControl ariaLabel="Sequence kind" value={sequence.kind} options={KIND_OPTIONS} onChange={switchKind} />
        </div>
        {sequence.kind === "numeric" && (
          <NumericFields sequence={sequence} errors={fieldErrors} onPatch={(p) => setSequence({ ...sequence, ...p })} />
        )}
        {sequence.kind === "alpha" && (
          <AlphaFields sequence={sequence} errors={fieldErrors} onPatch={(p) => setSequence({ ...sequence, ...p })} />
        )}
        {sequence.kind === "list" && (
          <ListValuesField values={sequence.values ?? []} error={fieldErrors.values} onChange={(v) => setSequence({ ...sequence, values: v })} />
        )}
        {expand.isError && (
          <p role="alert" className={errorText}>
            {expand.error instanceof ApiError ? expand.error.message : "Could not expand the sequence."}
          </p>
        )}

        <fieldset>
          <legend className={fieldLabelText}>Tags</legend>
          {tags.isError ? (
            <p role="alert" className={errorText}>
              {tags.error instanceof ApiError ? tags.error.message : "Could not load tags."}
            </p>
          ) : (tags.data ?? []).length === 0 ? (
            <p className={helpText}>{tags.isPending ? "Loading tags…" : "No tags in HomeBox."}</p>
          ) : (
            <div className="mt-1 flex max-h-32 flex-wrap gap-x-4 gap-y-1 overflow-y-auto">
              {tags.data!.map((tag) => (
                <label key={tag.id} className="flex items-center gap-2 text-[13px] text-deck-200">
                  <input type="checkbox" checked={tagIds.has(tag.id)} onChange={() => toggleTag(tag.id)} className={checkboxClass} />
                  {tag.name}
                </label>
              ))}
            </div>
          )}
        </fieldset>

        <div className="flex flex-wrap items-end gap-4">
          <div>
            <label htmlFor="bulk-label-type" className={`${fieldLabelText} mb-1`}>
              Label type
            </label>
            <Select id="bulk-label-type" value={labelKind} onChange={(v) => setLabelKind(v as HomeboxLabelKind)} options={LABEL_TYPE_OPTIONS} />
          </div>
          <Switch id="bulk-show-qr" checked={showQr} onChange={setShowQr} label="Show QR" />
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button type="button" onClick={() => void run()} disabled={!canRun} className={primaryButtonClass}>
            {bulk.isPending ? "Creating…" : `Create ${names.length || count} & print`}
          </button>
          {problem && <p className={helpText}>{problem}</p>}
        </div>

        {bulk.isError && (
          <p role="alert" className={errorText}>
            {bulk.error instanceof ApiError ? bulk.error.message : "Bulk create failed."}
          </p>
        )}
        {printError && (
          <p role="alert" className={errorText}>
            {printError}
          </p>
        )}

        {results && (
          <div>
            <p role="status" className="mb-2 text-[13px] text-deck-200">
              Created {okCount} of {results.length}
              {okCount > 0 && " -- labels added to the tray"}
            </p>
            <table className="w-full text-left text-[12px]">
              <thead className="text-deck-400">
                <tr>
                  <th className="py-1 pr-3">#</th>
                  <th className="py-1 pr-3">Name</th>
                  <th className="py-1 pr-3">Asset ID</th>
                  <th className="py-1">Result</th>
                </tr>
              </thead>
              <tbody>
                {results.map((row) => (
                  <tr key={row.index} className="border-t border-deck-800">
                    <td className="py-1 pr-3 font-mono">{row.index + 1}</td>
                    <td className="py-1 pr-3 text-deck-200">{row.entity?.name ?? names[row.index]}</td>
                    <td className="py-1 pr-3 font-mono">{row.entity?.asset_id ?? ""}</td>
                    <td className={`py-1 ${row.ok ? "text-sage-400" : "text-rust-500"}`}>{row.ok ? "Created" : (row.error ?? "Failed")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
