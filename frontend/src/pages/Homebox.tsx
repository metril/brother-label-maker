import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ApiError, getHomeboxEntityPath, getHomeboxSettings } from "../api/client";
import { HomeboxBulkCreate } from "../components/HomeboxBulkCreate";
import { HomeboxEntityRow } from "../components/HomeboxEntityRow";
import { HomeboxLocationTree } from "../components/HomeboxLocationTree";
import { Pending } from "../components/ui/Pending";
import { TextInput } from "../components/ui/inputs";
import {
  checkboxClass,
  errorText,
  fieldLabelText,
  iconButtonClass,
  panel,
  panelHeading,
  primaryButtonClass,
  typeHeading,
} from "../components/ui/styles";
import { useHomeboxAssetMatches, useHomeboxEntities } from "../hooks/useHomeboxEntities";
import { useSettingsQuery } from "../hooks/useSettings";
import { useHomeboxStatus } from "../hooks/useHomeboxStatus";
import { useHomeboxTree } from "../hooks/useHomeboxTree";
import {
  buildBreadcrumb,
  buildHomeboxCableLabelDefinition,
  buildHomeboxLabelDefinition,
  describeHomeboxEntity,
  matchesAssetIdShape,
  type HomeboxLabelKind,
} from "../lib/homebox";
import { useDesignerStore } from "../stores/designer";
import { useTrayStore } from "../stores/tray";
import type { HomeboxEntitySummary, HomeboxTreeItem } from "../api/types";

const SEARCH_DEBOUNCE_MS = 300;
const PAGE_SIZE = 50;

/** The HomeBox browse page (task 3.4): a left location tree driving
 * `parent_id`, a debounced search box driving `q` (both combine server-side,
 * see api/router_homebox.py's list_entities), a paginated results list with
 * multi-select, and "Add N to tray" -- the ONE way this page hands labels to
 * the SAME job tray Designer.tsx's own "Add to tray" uses (stores/tray.ts,
 * no parallel mechanism). Unreachable outside GET /api/homebox/status
 * reporting `configured` (AppShell's own nav gate); a direct visit while
 * unconfigured still renders its own explanatory empty state below, rather
 * than 404ing or crashing on the routes' own 503s. */
export function Homebox() {
  const status = useHomeboxStatus();
  const tape = useDesignerStore((s) => s.tape);
  const addTrayItem = useTrayStore((s) => s.addItem);

  const [selectedLocation, setSelectedLocation] = useState<{ id: string; name: string } | null>(null);
  const [rawQuery, setRawQuery] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Map<string, HomeboxEntitySummary>>(new Map());
  const [labelKinds, setLabelKinds] = useState<Record<string, HomeboxLabelKind>>({});
  const [addedCount, setAddedCount] = useState<number | null>(null);

  useEffect(() => {
    const handle = setTimeout(() => {
      setQ(rawQuery);
      setPage(1);
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [rawQuery]);

  // Every hook below is called unconditionally, on every render, same
  // "Rules of Hooks" discipline pages/Designer.tsx documents for its own
  // early return -- only the render branch further down (and each hook's
  // own `enabled`) reacts to `statusReady`.
  const statusData = status.data;
  const statusReady = statusData?.configured === true && statusData.reachable === true && statusData.healthy === true;
  const isAssetIdShape = matchesAssetIdShape(q);

  const settingsQuery = useSettingsQuery();
  const writesEnabled = settingsQuery.data?.settings.find((row) => row.key === "homebox_writes_enabled")?.value === true;

  const tree = useHomeboxTree(statusReady);
  const entities = useHomeboxEntities({
    q: q || undefined,
    page,
    pageSize: PAGE_SIZE,
    parentId: selectedLocation?.id,
    enabled: statusReady,
  });
  const assetMatches = useHomeboxAssetMatches(q, statusReady);

  const addToTrayMutation = useMutation({
    mutationFn: async (targets: HomeboxEntitySummary[]) => {
      const settings = await getHomeboxSettings();
      const paths = await Promise.all(targets.map((entity) => getHomeboxEntityPath(entity.id)));
      // structuredClone: a tray item is a frozen copy (stores/tray.ts) --
      // Designer.tsx clones its definition the same way, so the live
      // designer-store tape object reference never leaks into the tray.
      return targets.map((entity, i) => {
        const kind = labelKinds[entity.id] ?? "homebox_asset";
        return kind === "homebox_asset"
          ? buildHomeboxLabelDefinition(entity, buildBreadcrumb(paths[i]!), settings.effective_qr_base_url, structuredClone(tape))
          : buildHomeboxCableLabelDefinition(entity, kind, settings.effective_qr_base_url, structuredClone(tape));
      });
    },
    onSuccess: (definitions, targets) => {
      definitions.forEach((definition, i) => {
        addTrayItem({ definition, png: null, lengthMm: null, label: describeHomeboxEntity(targets[i]!) });
      });
      setAddedCount(targets.length);
      setSelected(new Map());
    },
  });

  function toggleSelect(entity: HomeboxEntitySummary) {
    setAddedCount(null);
    setSelected((prev) => {
      const next = new Map(prev);
      if (next.has(entity.id)) {
        next.delete(entity.id);
      } else {
        next.set(entity.id, entity);
      }
      return next;
    });
  }

  function toggleSelectAllOnPage() {
    const pageItems = entities.data?.items ?? [];
    setAddedCount(null);
    setSelected((prev) => {
      const allSelected = pageItems.length > 0 && pageItems.every((e) => prev.has(e.id));
      const next = new Map(prev);
      if (allSelected) {
        pageItems.forEach((e) => next.delete(e.id));
      } else {
        pageItems.forEach((e) => next.set(e.id, e));
      }
      return next;
    });
  }

  function selectLocation(node: HomeboxTreeItem | null) {
    setSelectedLocation(node ? { id: node.id, name: node.name } : null);
    setPage(1);
  }

  if (status.isPending) {
    return (
      <div className={panel}>
        <Pending />
      </div>
    );
  }

  if (status.isError || !statusData) {
    return (
      <div className="mx-auto flex max-w-6xl flex-col gap-6">
        <h1 className={typeHeading}>HomeBox</h1>
        <div className={panel}>
          <p role="alert" className={errorText}>
            Could not load HomeBox's own status.
          </p>
        </div>
      </div>
    );
  }

  if (!statusData.configured) {
    return (
      <div className="mx-auto flex max-w-6xl flex-col gap-6">
        <h1 className={typeHeading}>HomeBox</h1>
        <div className={panel}>
          <p className="text-[13px] text-deck-400">
            HomeBox isn't configured yet. Set <code className="font-mono text-deck-200">HOMEBOX_URL</code> (the instance's own
            root URL) and <code className="font-mono text-deck-200">HOMEBOX_API_KEY</code> (an{" "}
            <code className="font-mono text-deck-200">hb_</code>-prefixed read-only API key, from HomeBox's own user settings)
            in this app's environment, then restart it.
          </p>
        </div>
      </div>
    );
  }

  if (statusData.reachable === false || statusData.healthy === false) {
    return (
      <div className="mx-auto flex max-w-6xl flex-col gap-6">
        <h1 className={typeHeading}>HomeBox</h1>
        <div className={panel}>
          <p role="alert" className={errorText}>
            {statusData.error ?? "HomeBox is configured but not reachable right now."}
          </p>
        </div>
      </div>
    );
  }

  const total = entities.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const isFiltered = q !== "" || selectedLocation !== null;
  const pageItems = entities.data?.items ?? [];
  const allOnPageSelected = pageItems.length > 0 && pageItems.every((e) => selected.has(e.id));

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 pb-24">
      <h1 className={typeHeading}>HomeBox</h1>

      <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
        <aside className={`${panel} lg:w-64 lg:shrink-0`}>
          <h2 className={panelHeading}>Locations</h2>
          {tree.isPending ? (
            <Pending />
          ) : tree.isError ? (
            <p role="alert" className={errorText}>
              {tree.error instanceof ApiError ? tree.error.message : "Could not load the location tree."}
            </p>
          ) : (
            <HomeboxLocationTree nodes={tree.data ?? []} selectedId={selectedLocation?.id ?? null} onSelect={selectLocation} />
          )}
        </aside>

        <div className="flex min-w-0 flex-1 flex-col gap-4">
          {writesEnabled && <HomeboxBulkCreate parent={selectedLocation} />}
          <div className={panel}>
            <label htmlFor="homebox-search" className={`${fieldLabelText} mb-1 block`}>
              Search
            </label>
            <TextInput
              id="homebox-search"
              value={rawQuery}
              onChange={setRawQuery}
              placeholder="Search by name, or an asset id like 000-001…"
            />
            {selectedLocation && (
              <p className="mt-2 text-[12px] text-deck-400">
                Filtering to <span className="text-deck-200">{selectedLocation.name}</span>{" "}
                <button type="button" onClick={() => selectLocation(null)} className="text-amber-300 hover:underline">
                  Clear
                </button>
              </p>
            )}
          </div>

          {isAssetIdShape && (
            <div className={panel}>
              <h2 className={panelHeading}>Asset ID matches</h2>
              {assetMatches.isPending ? (
                <Pending />
              ) : assetMatches.isError ? (
                <p role="alert" className={errorText}>
                  {assetMatches.error instanceof ApiError ? assetMatches.error.message : "Could not look up this asset id."}
                </p>
              ) : assetMatches.data.length === 0 ? (
                <p className="text-[13px] text-deck-400">No asset with this id.</p>
              ) : (
                <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {assetMatches.data.map((entity) => (
                    <HomeboxEntityRow
                      key={entity.id}
                      entity={entity}
                      checked={selected.has(entity.id)}
                      onToggle={() => toggleSelect(entity)}
                      labelKind={labelKinds[entity.id] ?? "homebox_asset"}
                      onLabelKindChange={(kind) => setLabelKinds((prev) => ({ ...prev, [entity.id]: kind }))}
                    />
                  ))}
                </ul>
              )}
            </div>
          )}

          <div className={panel}>
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className={panelHeading}>Entities</h2>
              {pageItems.length > 0 && (
                <label className="flex items-center gap-2 text-[12px] text-deck-400">
                  <input
                    type="checkbox"
                    checked={allOnPageSelected}
                    onChange={toggleSelectAllOnPage}
                    className={checkboxClass}
                  />
                  Select all on page
                </label>
              )}
            </div>

            {entities.isPending ? (
              <Pending />
            ) : entities.isError ? (
              <p role="alert" className={errorText}>
                {entities.error instanceof ApiError ? entities.error.message : "Could not load HomeBox entities."}
              </p>
            ) : pageItems.length === 0 ? (
              <p className="text-[13px] text-deck-400">{isFiltered ? "No entities match this search." : "No entities to show."}</p>
            ) : (
              <>
                <ul className="flex flex-col gap-2">
                  {pageItems.map((entity) => (
                    <HomeboxEntityRow
                      key={entity.id}
                      entity={entity}
                      checked={selected.has(entity.id)}
                      onToggle={() => toggleSelect(entity)}
                      labelKind={labelKinds[entity.id] ?? "homebox_asset"}
                      onLabelKindChange={(kind) => setLabelKinds((prev) => ({ ...prev, [entity.id]: kind }))}
                    />
                  ))}
                </ul>
                <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                  <p className="font-mono text-[12px] text-deck-400">
                    Page {entities.data!.page} of {totalPages} · {total} entit{total === 1 ? "y" : "ies"}
                  </p>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      disabled={page <= 1}
                      className={iconButtonClass}
                      aria-label="Previous page"
                    >
                      ‹
                    </button>
                    <button
                      type="button"
                      onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                      disabled={page >= totalPages}
                      className={iconButtonClass}
                      aria-label="Next page"
                    >
                      ›
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {addedCount !== null && selected.size === 0 && (
        <p role="status" className="text-[13px] text-sage-400">
          Added {addedCount} label{addedCount === 1 ? "" : "s"} to tray
        </p>
      )}

      {selected.size > 0 && (
        <div className="sticky bottom-4 z-10 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-500/40 bg-deck-900 px-4 py-3 shadow-lg">
          <p className="text-[13px] text-deck-200">
            {selected.size} selected
            <button type="button" onClick={() => setSelected(new Map())} className="ml-3 text-[12px] text-deck-400 hover:text-deck-200">
              Clear
            </button>
          </p>
          <div className="flex items-center gap-3">
            {addToTrayMutation.isError && (
              <p role="alert" className={errorText}>
                {addToTrayMutation.error instanceof ApiError ? addToTrayMutation.error.message : "Could not add to tray."}
              </p>
            )}
            <button
              type="button"
              onClick={() => addToTrayMutation.mutate([...selected.values()])}
              disabled={addToTrayMutation.isPending}
              className={primaryButtonClass}
            >
              {addToTrayMutation.isPending ? "Adding…" : `Add ${selected.size} to tray`}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
