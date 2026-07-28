import { StatusChip } from "./StatusChip";
import { statusFromEvent } from "../lib/jobStatus";
import { formatAbsoluteTime, formatRelativeTime } from "../lib/time";
import { humanizeEnumValue } from "../schema/humanize";
import type { HistoryItem, JobEvent } from "../api/types";

interface HistoryRowProps {
  item: HistoryItem;
  /** The latest WS event for THIS row's own job id, if any -- overlays
   * `item.status` for display (see StatusChip.tsx's statusFromEvent) so a
   * job that transitions while the page is open updates in place, without
   * waiting on a refetch. */
  liveEvent?: JobEvent;
  reprintJobId: string | null;
  reprintEvent?: JobEvent;
  reprintPending: boolean;
  onReprint: () => void;
  onDetails: () => void;
  onDelete: () => void;
}

/** One row of the History table (task 2.13) -- thumbnail, relative+
 * absolute created_at, a live-updating status chip (+ byte progress while
 * printing), the numbers the design doc calls for (label_count/chain_mode/
 * tape width/tape_used_mm, all mono), the failure text when there is one,
 * and the three row actions. */
export function HistoryRow({ item, liveEvent, reprintJobId, reprintEvent, reprintPending, onReprint, onDetails, onDelete }: HistoryRowProps) {
  const status = liveEvent ? statusFromEvent(liveEvent.event) : item.status;
  const progressPct =
    liveEvent?.event === "job.progress" && liveEvent.sent !== undefined && liveEvent.total !== undefined && liveEvent.total > 0
      ? Math.round((liveEvent.sent / liveEvent.total) * 100)
      : null;

  return (
    <tr className="border-b border-deck-800/60 align-top">
      <td className="py-2 pr-3">
        <div className="flex h-9 w-14 items-center justify-center overflow-hidden rounded-sm" style={{ backgroundColor: "var(--color-tape)" }}>
          {item.thumbnail_url ? (
            <img
              src={item.thumbnail_url}
              alt=""
              loading="lazy"
              style={{ imageRendering: "pixelated", maxHeight: "100%", maxWidth: "100%" }}
            />
          ) : null}
        </div>
      </td>
      <td className="py-2 pr-3 font-mono text-[12px] text-deck-200">
        <time dateTime={item.created_at} title={formatAbsoluteTime(item.created_at)}>
          {formatRelativeTime(item.created_at)}
        </time>
      </td>
      <td className="py-2 pr-3">
        <div className="flex items-center gap-1.5">
          <StatusChip status={status} />
          {progressPct !== null && status === "printing" && <span className="font-mono text-[11px] text-deck-400">{progressPct}%</span>}
        </div>
        {status === "failed" && item.error && (
          <p className="mt-1 max-w-[220px] truncate text-[11px] text-rust-500" title={item.error}>
            {item.error}
          </p>
        )}
      </td>
      <td className="py-2 pr-3 font-mono text-[12px] text-deck-200">{item.label_count}</td>
      <td className="py-2 pr-3 text-[12px] text-deck-200">{humanizeEnumValue(item.chain_mode)}</td>
      <td className="py-2 pr-3 font-mono text-[12px] text-deck-200">{item.tape_width_mm != null ? `${item.tape_width_mm}mm` : "—"}</td>
      <td className="py-2 pr-3 font-mono text-[12px] text-deck-200">{item.tape_used_mm != null ? `${item.tape_used_mm.toFixed(1)} mm` : "—"}</td>
      <td className="py-2 pr-3">
        <div className="flex flex-col items-start gap-1">
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={onReprint}
              disabled={reprintPending}
              className="text-[12px] font-medium text-amber-300 hover:underline disabled:opacity-50"
            >
              Reprint
            </button>
            <button type="button" onClick={onDetails} className="text-[12px] font-medium text-deck-200 hover:underline">
              Details
            </button>
            <button type="button" onClick={onDelete} className="text-[12px] font-medium text-rust-500 hover:underline">
              Delete
            </button>
          </div>
          {reprintJobId && <StatusChip status={reprintEvent ? statusFromEvent(reprintEvent.event) : "queued"} />}
        </div>
      </td>
    </tr>
  );
}
