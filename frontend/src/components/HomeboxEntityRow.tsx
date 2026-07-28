import type { HomeboxEntitySummary } from "../api/types";

interface HomeboxEntityRowProps {
  entity: HomeboxEntitySummary;
  checked: boolean;
  onToggle: () => void;
}

/** One HomeBox entity row (task 3.4's browse page, both the normal results
 * list and the "Asset ID matches" disambiguation section): a checkbox
 * (multi-select toward "Add N to tray"), the entity's name, its asset id
 * (JetBrains Mono -- a machine value, this app's own convention for every
 * id/measurement), an Item/Location chip (`entity_type.is_location`), and
 * its immediate parent's name when it has one. */
export function HomeboxEntityRow({ entity, checked, onToggle }: HomeboxEntityRowProps) {
  const isLocation = entity.entity_type?.is_location ?? false;

  return (
    <li className="flex items-center gap-3 rounded-lg border border-deck-800 bg-deck-900/40 px-3 py-2">
      <input
        type="checkbox"
        checked={checked}
        onChange={onToggle}
        aria-label={`Select ${entity.name}`}
        className="h-4 w-4 shrink-0 rounded border-deck-600 bg-deck-800 accent-amber-500"
      />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[14px] text-deck-200" title={entity.name}>
          {entity.name}
        </p>
        <div className="mt-0.5 flex flex-wrap items-center gap-2">
          {entity.asset_id && <span className="font-mono text-[11px] text-deck-400">{entity.asset_id}</span>}
          <span className="rounded border border-deck-600 px-1.5 py-0.5 font-condensed text-[10px] uppercase tracking-wide text-deck-400">
            {isLocation ? "Location" : "Item"}
          </span>
          {entity.parent && (
            <span className="truncate text-[11px] text-deck-400" title={entity.parent.name}>
              in {entity.parent.name}
            </span>
          )}
        </div>
      </div>
    </li>
  );
}
