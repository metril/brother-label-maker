import { checkboxClass } from "./ui/styles";
import type { HomeboxEntitySummary } from "../api/types";
import type { HomeboxLabelKind } from "../lib/homebox";

const LABEL_KIND_OPTIONS: { value: HomeboxLabelKind; label: string }[] = [
  { value: "homebox_asset", label: "Asset label" },
  { value: "cable_wrap", label: "Cable wrap" },
  { value: "cable_flag", label: "Cable flag" },
];

interface HomeboxEntityRowProps {
  entity: HomeboxEntitySummary;
  checked: boolean;
  onToggle: () => void;
  /** Label type "Add to tray" builds for this row; the picker only renders
   * when `onLabelKindChange` is given. Defaults to the asset label. */
  labelKind?: HomeboxLabelKind;
  onLabelKindChange?: (kind: HomeboxLabelKind) => void;
}

/** One HomeBox entity row (task 3.4's browse page, both the normal results
 * list and the "Asset ID matches" disambiguation section): a checkbox
 * (multi-select toward "Add N to tray"), the entity's name, its asset id
 * (JetBrains Mono -- a machine value, this app's own convention for every
 * id/measurement), an Item/Location chip (`entity_type.is_location`), and
 * its immediate parent's name when it has one. */
export function HomeboxEntityRow({ entity, checked, onToggle, labelKind = "homebox_asset", onLabelKindChange }: HomeboxEntityRowProps) {
  const isLocation = entity.entity_type?.is_location ?? false;

  return (
    <li className="flex items-center gap-3 rounded-lg border border-deck-800 bg-deck-900/40 px-3 py-2">
      <input
        type="checkbox"
        checked={checked}
        onChange={onToggle}
        aria-label={`Select ${entity.name}`}
        className={`${checkboxClass} shrink-0`}
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
      {onLabelKindChange && (
        <select
          value={labelKind}
          onChange={(e) => onLabelKindChange(e.target.value as HomeboxLabelKind)}
          aria-label={`Label type for ${entity.name}`}
          className="shrink-0 rounded border border-deck-700 bg-deck-900 px-1.5 py-1 text-[12px] text-deck-200"
        >
          {LABEL_KIND_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      )}
    </li>
  );
}
