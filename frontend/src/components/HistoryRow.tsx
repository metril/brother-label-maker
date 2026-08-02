import { StatusChip } from "./StatusChip";
import { statusFromEvent } from "../lib/jobStatus";
import { errorText } from "./ui/styles";
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
  /** Review fix-up: POST .../reprint's own two real failure modes (404 --
   * deleted out-of-band; 409 -- a stored definition that no longer
   * validates, router_history.py's reprint_job docstring) used to be
   * completely silent (no role="alert", no chip, nothing). Non-null only
   * while the LAST reprint attempt for this row failed and hasn't been
   * superseded by a successful one (see pages/History.tsx's own
   * reprintErrors state). */
  reprintError: string | null;
  onReprint: () => void;
  onDetails: () => void;
  onDelete: () => void;
}

/** One row of the History table (task 2.13) -- thumbnail, relative+
 * absolute created_at, a live-updating status chip (+ byte progress while
 * printing), the numbers the design doc calls for (label_count/chain_mode/
 * tape width/tape_used_mm, all mono), the failure text when there is one,
 * and the three row actions. */
export function HistoryRow({
  item,
  liveEvent,
  reprintJobId,
  reprintEvent,
  reprintPending,
  reprintError,
  onReprint,
  onDetails,
  onDelete,
}: HistoryRowProps) {
  const status = liveEvent ? statusFromEvent(liveEvent.event) : item.status;
  const progressPct =
    liveEvent?.event === "job.progress" && liveEvent.sent !== undefined && liveEvent.total !== undefined && liveEvent.total > 0
      ? Math.round((liveEvent.sent / liveEvent.total) * 100)
      : null;
  // Task 4.3 fix-up: this used to be `job ${index + 1}` -- the row's
  // position on the CURRENT page, not anything about the job itself. A
  // live status transition (this page's own WS overlay, above) or a
  // filter/page-size change re-sorts or re-pages the list at any moment,
  // which silently RE-TARGETS "Reprint job 3" at a different job than the
  // one a screen-reader user just heard announced -- and made a query like
  // `getByRole("button", { name: "Reprint job 1" })` describe "whichever
  // job is first" rather than a specific job. `item.id` is the row's own
  // stable key (already what `<HistoryRow key={item.id} .../>` uses) and
  // never changes for as long as the row exists, regardless of sort order
  // -- and per the design doc's own type rules, a raw job id is exactly the
  // kind of machine value this app is meant to expose as-is (see
  // pages/Diagnostics.tsx's Print-worker section, which shows `job.id` the
  // same unstyled way).
  const rowLabel = `job ${item.id}`;

  return (
    <tr className="border-b border-deck-800/60 align-top">
      <td className="py-2 pr-3">
        <div className="flex h-9 w-14 items-center justify-center overflow-hidden rounded-sm border border-deck-600/50" style={{ backgroundColor: "var(--color-tape)" }}>
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
        <div className="flex max-w-[220px] flex-col items-start gap-1">
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={onReprint}
              disabled={reprintPending}
              aria-label={`Reprint ${rowLabel}`}
              className="text-[12px] font-medium text-amber-300 hover:underline disabled:opacity-50"
            >
              Reprint
            </button>
            <button
              type="button"
              onClick={onDetails}
              aria-label={`View details for ${rowLabel}`}
              className="text-[12px] font-medium text-deck-200 hover:underline"
            >
              Details
            </button>
            <button
              type="button"
              onClick={onDelete}
              aria-label={`Delete ${rowLabel}`}
              className="text-[12px] font-medium text-rust-500 hover:underline"
            >
              Delete
            </button>
          </div>
          {reprintError && (
            <p role="alert" className={`${errorText} mt-0`}>
              {reprintError}
            </p>
          )}
          {reprintJobId && <StatusChip status={reprintEvent ? statusFromEvent(reprintEvent.event) : "queued"} />}
        </div>
      </td>
    </tr>
  );
}
