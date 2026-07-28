import type { UsePrintJobResult } from "../hooks/usePrintJob";
import { errorText } from "./ui/styles";
import type { LabelDefinition, PrintOptions, Sequence } from "../api/types";

interface PrintButtonProps {
  /** Task 2.12: the job's OWN lifecycle state, from a SINGLE `usePrintJob()`
   * call made once in JobTray.tsx -- not owned here, so the desktop panel
   * and the mobile compact bar (both of which render a PrintButton) always
   * agree about what's currently in flight instead of each tracking its
   * own, independently-polled job. */
  job: UsePrintJobResult;
  /** The exact `labels` array POST /api/print's body will carry -- either
   * the tray's own item definitions, or a one-element array wrapping the
   * current (unsaved) design when the tray is empty (see JobTray.tsx's
   * `bodyLabels`). */
  labels: LabelDefinition[];
  options: PrintOptions;
  /** task 2.11: the confirmed serialization spec -- null on every tray path
   * (mutually exclusive with a non-empty tray; see JobTray.tsx) and on the
   * plain empty-tray path with serialization off. */
  serialization?: Sequence | null;
  /** The confirmed total label count for `serialization`; null otherwise. */
  totalLabels?: number | null;
  /** True when `labels` came from a non-empty tray (as opposed to the
   * empty-tray "just print the current design" path) -- purely a label-
   * wording flag ("(tray)" suffix, brief's own "Print 4 labels (tray)"
   * example): `labels.length` alone can't distinguish a one-ITEM tray from
   * the plain single-design path, both of which send a one-element array. */
  isTray?: boolean;
  disabled?: boolean;
  /** task 2.12 carry-forward: serialization + a non-empty tray are
   * mutually exclusive server-side (POST /api/print requires exactly one
   * template label when `serialization` is set) -- when set, Print is
   * blocked and this message shown instead of ever attempting the request. */
  blockedMessage?: string | null;
}

function idleLabel(labels: LabelDefinition[], serialization: Sequence | null, totalLabels: number | null, isTray: boolean): string {
  if (serialization && totalLabels != null) {
    return `Print ${totalLabels} label${totalLabels === 1 ? "" : "s"}`;
  }
  const n = labels.length;
  return `Print ${n} label${n === 1 ? "" : "s"}${isTray ? " (tray)" : ""}`;
}

function ProgressBar({ sent, total }: { sent: number; total: number }) {
  const pct = total > 0 ? Math.min(100, Math.round((sent / total) * 100)) : 0;
  return (
    <div
      role="progressbar"
      aria-label="Print progress"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-deck-800"
    >
      <div className="h-full rounded-full bg-amber-500" style={{ width: `${pct}%` }} />
    </div>
  );
}

/** The Print action itself: submits `labels`/`options`/`serialization` via
 * `job.submit`, then renders `job`'s own phase as a progress bar (driven by
 * `job.progress`'s WS `job.progress` bytes) with a Cancel button enabled
 * only while `job.canCancel` (the CAS contract's "still queued" window --
 * see hooks/usePrintJob.ts), a success line + "Print again" on done, and
 * the job's error (kept, tray intact) on failure. */
export function PrintButton({
  job,
  labels,
  options,
  serialization = null,
  totalLabels = null,
  isTray = false,
  disabled,
  blockedMessage = null,
}: PrintButtonProps) {
  const active = job.phase === "queued" || job.phase === "printing";
  const busy = job.isSubmitting || active;

  // The count to show RIGHT NOW if the user clicked print this instant --
  // always derived from LIVE props, since it drives the idle/queued/
  // printing label (which must track the tray/design as it's edited).
  const liveCount = serialization && totalLabels != null ? totalLabels : labels.length;

  function handleClick() {
    if (busy || disabled || blockedMessage) return;
    job.submit({ labels, options, serialization: serialization ?? undefined }, liveCount);
  }

  // Review fix-up (2nd round): `job.printedBodyStale` -- true once done AND
  // the live body no longer matches what was submitted (the tray was
  // edited, even while still printing) -- suppresses JUST the "Print
  // again" label/styling, falling through to the same live, count-bearing
  // `idleLabel` the idle/queued/printing states already use. The done-state
  // SUCCESS LINE below is untouched by this: it stays visible with its own
  // frozen count regardless of staleness (see hooks/usePrintJob.ts's own
  // docstring for why reverting `phase` itself used to swallow that
  // confirmation entirely for a body edited mid-print).
  let label = idleLabel(labels, serialization, totalLabels, isTray);
  if (job.isSubmitting) label = "Sending…";
  else if (job.phase === "queued") label = "Queued…";
  else if (job.phase === "printing") label = "Printing…";
  else if (job.phase === "done" && !job.printedBodyStale) label = "Print again";

  const buttonClass =
    job.phase === "done" && !job.printedBodyStale
      ? "border-sage-400 bg-sage-400/15 text-sage-400"
      : job.phase === "failed"
        ? "border-rust-500 bg-rust-500/15 text-rust-500"
        : "border-amber-500 bg-amber-500 text-deck-950 hover:bg-amber-300";

  // Review fix-up: the done-state success line must describe the job that
  // ACTUALLY printed, not whatever the tray/current design happens to look
  // like right now -- `job.submittedCount` is frozen by usePrintJob at the
  // moment `submit()` was called (see that hook's own docstring); using
  // `liveCount` here instead let duplicating/removing tray items AFTER a
  // print finished silently rewrite this role="status" region (confirmed
  // live: "Printed 2 labels." became "Printed 64 labels." after
  // duplicating the tray post-print -- the job that actually printed still
  // only had 2). Falls back to `liveCount` only for the impossible case of
  // `phase === "done"` with a null `submittedCount` (never happens via
  // this component's own `submit` call, which always supplies one).
  const printedCount = job.submittedCount ?? liveCount;

  return (
    <div className="flex w-full flex-col items-start gap-2">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={handleClick}
          disabled={busy || disabled || blockedMessage !== null}
          className={`rounded-md border px-5 py-2 text-[14px] font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${buttonClass}`}
        >
          {label}
        </button>
        {active && (
          <button
            type="button"
            onClick={job.cancel}
            disabled={!job.canCancel || job.isCanceling}
            className="rounded-md border border-deck-600 bg-deck-800 px-3 py-2 text-[13px] font-medium text-deck-200 transition-colors hover:border-deck-400 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {job.isCanceling ? "Canceling…" : "Cancel"}
          </button>
        )}
      </div>

      {blockedMessage && (
        <p role="alert" className={errorText}>
          {blockedMessage}
        </p>
      )}

      {active && (
        <div className="w-full">
          <p className="font-mono text-[11px] text-deck-400">
            {job.phase === "queued" ? "Queued" : "Printing"}
            {job.progress ? ` — ${Math.min(100, Math.round((job.progress.sent / job.progress.total) * 100))}%` : "…"}
          </p>
          <ProgressBar sent={job.progress?.sent ?? 0} total={job.progress?.total ?? 0} />
        </div>
      )}

      {job.phase === "done" && (
        <p role="status" className="text-[12px] text-sage-400">
          Printed {printedCount} label{printedCount === 1 ? "" : "s"}.
        </p>
      )}

      {job.phase === "failed" && job.errorText && (
        <p role="alert" className={errorText}>
          {job.errorText}
        </p>
      )}

      {job.cancelError && (
        <p role="alert" className={errorText}>
          {job.cancelError}
        </p>
      )}
    </div>
  );
}
