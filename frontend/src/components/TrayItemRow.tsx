import { indexBadge, iconButtonClass } from "./ui/styles";
import type { TrayPreview } from "../hooks/useTrayPreviews";
import type { TrayItem } from "../stores/tray";

interface TrayItemRowProps {
  item: TrayItem;
  index: number;
  isFirst: boolean;
  isLast: boolean;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onDuplicate: () => void;
  onRemove: () => void;
  /** A fetched-on-demand preview (hooks/useTrayPreviews.ts) for an item
   * queued with no png/lengthMm of its own (e.g. pages/Homebox.tsx's "Add
   * to tray") -- undefined while still loading, on the item's own captured
   * preview already being present, or on a fetch failure (the blank swatch/
   * "···" length fallback below covers all three the same way). */
  hydratedPreview?: TrayPreview;
}

/** One queued label in the Job tray: a small thumbnail (the exact preview
 * PNG captured when it was added to the tray -- never re-rendered), its
 * short "type + first text line" caption, length, and the reorder/
 * duplicate/remove controls (up/down buttons per WCAG 2.5.7, same
 * convention as SchemaField's own repeatable rows -- see
 * components/schema/ArrayOfObjects.tsx).
 *
 * Two rows, not one: the sidebar is only `lg:w-80` (320px, minus padding),
 * and a badge + thumbnail + label + length + four icon buttons all on one
 * line left almost no room for the label -- it truncated down to a
 * character or two and wrapped badly (confirmed live). Splitting the four
 * controls onto their own row underneath gives the label column real width
 * to breathe. */
export function TrayItemRow({
  item,
  index,
  isFirst,
  isLast,
  onMoveUp,
  onMoveDown,
  onDuplicate,
  onRemove,
  hydratedPreview,
}: TrayItemRowProps) {
  const png = item.png ?? hydratedPreview?.png ?? null;
  const lengthMm = item.lengthMm ?? hydratedPreview?.lengthMm ?? null;

  return (
    <li className="flex flex-col gap-2 rounded-lg border border-deck-700 bg-deck-800/40 p-2">
      <div className="flex items-center gap-2">
        <span className={indexBadge}>{index + 1}</span>
        <div
          className="flex h-7 w-10 shrink-0 items-center justify-center overflow-hidden rounded-sm border border-deck-600/50"
          style={{ backgroundColor: "var(--color-tape)" }}
        >
          {png ? <img src={png} alt="" style={{ imageRendering: "pixelated", maxHeight: "100%", maxWidth: "100%" }} /> : null}
        </div>
        {/* title: the 320px sidebar still truncates a longer caption (e.g.
            "Patch Panel — PP-RACK-3" -> "Patch Panel — PP…") -- a native
            tooltip is the cheap fix for the full text on HOVER (a plain
            `title` attribute is mouse-only, not a keyboard/focus
            affordance -- corrected wording, review fix-up) without
            re-fighting the row's already-tight layout budget. */}
        <p className="min-w-0 flex-1 truncate text-[13px] text-deck-200" title={item.label}>
          {item.label}
        </p>
        <span className="shrink-0 font-mono text-[11px] text-deck-400">{lengthMm !== null ? `${lengthMm.toFixed(1)} mm` : "···"}</span>
      </div>
      <div className="flex justify-end gap-1">
        <button type="button" aria-label={`Move item ${index + 1} up`} disabled={isFirst} onClick={onMoveUp} className={iconButtonClass}>
          ↑
        </button>
        <button type="button" aria-label={`Move item ${index + 1} down`} disabled={isLast} onClick={onMoveDown} className={iconButtonClass}>
          ↓
        </button>
        <button type="button" aria-label={`Duplicate item ${index + 1}`} onClick={onDuplicate} className={iconButtonClass}>
          ⧉
        </button>
        <button type="button" aria-label={`Remove item ${index + 1}`} onClick={onRemove} className={iconButtonClass}>
          ×
        </button>
      </div>
    </li>
  );
}
