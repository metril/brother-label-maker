import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ApiError, getPrintJob, postCancelPrintJob, postPrint } from "../api/client";
import { useJobEvent } from "./useJobEvents";
import type { PrintRequest } from "../api/types";

const POLL_INTERVAL_MS = 1000;
const POLL_TIMEOUT_MS = 30_000;

export type PrintJobPhase = "idle" | "queued" | "printing" | "done" | "failed";

export interface PrintJobProgress {
  sent: number;
  total: number;
}

export interface UsePrintJobResult {
  phase: PrintJobPhase;
  jobId: string | null;
  /** Bytes of the job's wire stream sent so far -- from `job.progress` WS
   * frames only (task 2.9's throttled ~11-broadcasts-per-job cadence, see
   * jobs/worker.py's _make_progress_cb); the poll fallback carries no byte
   * count, so this stays at its last known value (or null, pre-first-frame)
   * while polling alone is driving the terminal-state detection below. */
  progress: PrintJobProgress | null;
  /** Set once phase reaches "failed" -- a request-time failure (the POST
   * itself 422ing), a `job.failed` event/poll, a `job.canceled` event/poll,
   * or the 30s no-status-activity watchdog timing out. */
  errorText: string | null;
  /** The human-facing label count FROZEN at the moment `submit()` was
   * called -- review fix-up: the done-state success line used to re-derive
   * this from the CALLER's live props (PrintButton's own `labels`/
   * `totalLabels`), so duplicating or removing a tray item after a print
   * finished silently rewrote a `role="status"` region describing a
   * COMPLETED machine action ("Printed 2 labels." became "Printed 64
   * labels." after duplicating the tray post-print, confirmed live -- the
   * job that actually printed always had 2). Null before the first submit. */
  submittedCount: number | null;
  /** True once `phase === "done"` if the live print body (the caller's
   * `bodyKey`, passed to this hook every render) no longer matches what
   * was ACTUALLY submitted -- e.g. the tray was edited after the print
   * finished, or even WHILE it was still printing. Review fix-up (2nd
   * round): this used to revert `phase` itself back to "idle" the instant
   * the body diverged -- which, for a body edited WHILE still printing,
   * meant the "done" transition and the "idle" revert landed in the SAME
   * commit the moment `job.done` arrived: the success line mounted and
   * unmounted within one render, so the user never saw a completion
   * notice at all (this WILL happen with a real printer, where a print
   * genuinely takes seconds -- plenty of time to edit the tray first).
   * `phase` now stays truthfully "done" regardless -- the job DID
   * complete -- and this flag exists purely so the CALLER can suppress
   * just the "Print again" button label (which would otherwise imply
   * re-submitting the SAME body) without ever hiding the frozen
   * `submittedCount` success line itself. */
  printedBodyStale: boolean;
  /** True only while the job's LAST KNOWN status is "queued" -- the CAS
   * contract's own window (router_print.py's cancel_print_job): once the
   * worker has dequeued it (phase -> "printing"), cancel always 409s, so
   * the UI disables the action rather than let the user fire a request
   * that's guaranteed to fail. */
  canCancel: boolean;
  isCanceling: boolean;
  /** The 409/404 message from a cancel attempt that didn't land (e.g. the
   * job had already started) -- shown inline, distinct from `errorText`
   * (the JOB's own terminal failure) since a failed CANCEL doesn't mean the
   * print itself failed. Review fix-up: used to persist indefinitely until
   * the NEXT submit -- now also cleared on `submit()` and once the job
   * reaches a TERMINAL state (done/failed). Deliberately NOT cleared on
   * every phase change (a 2nd-round regression the first fix introduced):
   * the realistic way this message exists at all is a 409 landing while
   * `phase` is still locally "queued", followed shortly by `job.started`
   * moving it to "printing" -- clearing on that transition wiped the
   * message before it could reasonably be read, sometimes within ~1s. */
  cancelError: string | null;
  isSubmitting: boolean;
  /** `printedCount`: the human-facing label count to freeze into
   * `submittedCount` for the done-state success line -- the CALLER already
   * computes this (PrintButton's own idle-label logic), so it's passed
   * through rather than re-derived here from `body` alone (which doesn't
   * carry a serialized run's expanded total, only its unexpanded spec). */
  submit: (body: PrintRequest, printedCount: number) => void;
  cancel: () => void;
}

/** The job tray's print-job lifecycle: POST /api/print, then track the job
 * to a terminal state two ways at once -- the shared WS event stream
 * (useJobEvent, live push) and a 1s poll of GET /api/print/jobs/{id} as a
 * fallback, whichever source reports a terminal status first wins -- plus
 * POST /api/print/jobs/{id}/cancel while the job is still queued. A REAL
 * timer (not query data) enforces a 30s cap on SILENCE (restarted by every
 * WS frame/successful poll) before a terminal state, same reasoning as the
 * original (pre-2.12) PrintButton.tsx: TanStack Query's structural sharing keeps `data` reference-stable across polls
 * that return an unchanged payload, so a derivation effect keyed off
 * `pollQuery.data` itself would silently stop re-running for a job stuck
 * reporting the same status forever.
 *
 * Extracted out of PrintButton.tsx (task 2.9-2.11's single-label component)
 * so ONE hook call -- made once, in JobTray.tsx -- can back BOTH the
 * detail panel's print section and the mobile compact bar's own status
 * label without opening a second WS-tracked/polled job or risking the two
 * disagreeing about what's currently in flight.
 *
 * `bodyKey` (review fix-up): a caller-computed signature of the CURRENT
 * print body (JobTray.tsx's own `JSON.stringify({bodyLabels, options,
 * bodySerialization})`), passed on every render -- NOT used to fire
 * anything itself, only compared (during render, no effect involved) against
 * the signature that was active at the moment of the last `submit()` call
 * to derive `printedBodyStale`. `failed`/`canceled` were never affected by
 * the bug this fixes (PrintButton's own label logic already falls back to
 * the live count outside the `done` branch) -- only `done` needed this. */
export function usePrintJob(bodyKey: string): UsePrintJobResult {
  const [phase, setPhase] = useState<PrintJobPhase>("idle");
  const [jobId, setJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState<PrintJobProgress | null>(null);
  const [errorText, setErrorText] = useState<string | null>(null);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [submittedCount, setSubmittedCount] = useState<number | null>(null);

  // The body signature that was active at the moment of the LAST submit()
  // call -- compared against the live `bodyKey` below to detect "the thing
  // the done state describes no longer matches what's on screen". A ref
  // (not state): it must never itself trigger a re-render, only be read
  // inside the comparison effect.
  const submittedBodyKeyRef = useRef<string | null>(null);

  const wsEvent = useJobEvent(jobId);
  const wsStatus = wsEvent?.event;
  const wsError = wsEvent?.error;
  const wsSent = wsEvent?.sent;
  const wsTotal = wsEvent?.total;

  const mutation = useMutation({
    mutationFn: (body: PrintRequest) => postPrint(body),
    onSuccess: (data) => {
      setJobId(data.job_id);
      setPhase("queued");
    },
    onError: (err) => {
      setPhase("failed");
      setErrorText(err instanceof ApiError ? err.message : "print request failed");
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (id: string) => postCancelPrintJob(id),
    onSuccess: () => {
      setCancelError(null);
      // The CAS itself is the source of truth (router_print.py): a 200
      // here means the job genuinely never started printing. job.canceled
      // still arrives over the WS/poll paths too (harmless double-set to
      // the same terminal state) -- this just doesn't wait for it.
      setPhase("failed");
      setErrorText("print job was canceled");
    },
    onError: (err) => {
      setCancelError(err instanceof ApiError ? err.message : "cancel request failed");
    },
  });

  const active = phase === "queued" || phase === "printing";

  const pollEnabled =
    active && jobId !== null && wsStatus !== "job.done" && wsStatus !== "job.failed" && wsStatus !== "job.canceled";

  const pollQuery = useQuery({
    queryKey: ["print-job-poll", jobId],
    queryFn: () => getPrintJob(jobId as string),
    enabled: pollEnabled,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "done" || status === "failed" || status === "canceled" ? false : POLL_INTERVAL_MS;
    },
  });

  // Read out only the PRIMITIVE fields the derivation below cares about --
  // see this module's own docstring on why (structural sharing keeping
  // `pollQuery.data` reference-stable across an unchanging status).
  const polledStatus = pollQuery.data?.status;
  const polledError = pollQuery.data?.error;
  const pollErrorMessage = pollQuery.error
    ? pollQuery.error instanceof ApiError
      ? pollQuery.error.message
      : "failed to check print status"
    : null;

  useEffect(() => {
    if (!active || !jobId) return;

    if (wsStatus === "job.started" || wsStatus === "job.progress") {
      setPhase((p) => (p === "queued" ? "printing" : p));
    }
    if (wsStatus === "job.progress" && wsSent !== undefined && wsTotal !== undefined) {
      setProgress({ sent: wsSent, total: wsTotal });
    }

    if (wsStatus === "job.done") {
      setPhase("done");
    } else if (wsStatus === "job.failed") {
      setPhase("failed");
      setErrorText(wsError ?? "print job failed");
    } else if (wsStatus === "job.canceled") {
      setPhase("failed");
      setErrorText("print job was canceled");
    } else if (polledStatus === "printing") {
      setPhase((p) => (p === "queued" ? "printing" : p));
    } else if (polledStatus === "done") {
      setPhase("done");
    } else if (polledStatus === "failed") {
      setPhase("failed");
      setErrorText(polledError ?? "print job failed");
    } else if (polledStatus === "canceled") {
      setPhase("failed");
      setErrorText("print job was canceled");
    } else if (pollErrorMessage) {
      setPhase("failed");
      setErrorText(pollErrorMessage);
    }
  }, [active, jobId, wsStatus, wsError, wsSent, wsTotal, polledStatus, polledError, pollErrorMessage]);

  // 30s of SILENCE cap -- a REAL timer, deliberately independent of any
  // query/WS data reference (see this module's own docstring), restarted on
  // every WS frame (`wsEvent` is a fresh object per frame) and every
  // successful poll (`dataUpdatedAt` ticks even when structural sharing
  // keeps `data` itself reference-stable). A long or queued-behind-others
  // print therefore never times out while status keeps arriving -- the old
  // fixed 30s-from-submit budget reported those as failed, which let the
  // user re-submit a job that was still going to print (duplicate print).
  const pollUpdatedAt = pollQuery.dataUpdatedAt;
  useEffect(() => {
    if (!active) return;
    const timer = setTimeout(() => {
      setPhase("failed");
      setErrorText("timed out waiting for print status");
    }, POLL_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [active, wsEvent, pollUpdatedAt]);

  // Review fix-up (2nd round): `printedBodyStale` is a PURE DERIVED value,
  // computed fresh on every render -- deliberately NOT a separate
  // useEffect+setState pair (see UsePrintJobResult's own docstring for the
  // "success line mounts and unmounts in the same commit" bug that
  // approach caused: an effect reacting to `phase` becoming "done" AND
  // `bodyKey` having already diverged -- e.g. the tray was edited WHILE
  // still printing -- fired in the same pass that `phase` itself was set
  // to "done", reverting it to "idle" before a single paint ever showed
  // the completion). Reading `submittedBodyKeyRef.current` here is safe:
  // it's write-only from `submit()` (an event handler), never written
  // during render, so it can only ever describe an EARLIER submit relative
  // to the render currently computing this value.
  const printedBodyStale =
    phase === "done" && submittedBodyKeyRef.current !== null && submittedBodyKeyRef.current !== bodyKey;

  // Review fix-up (2nd round): a cancel attempt's 409/404 message must
  // outlive the ROUTINE phase transition it's often diagnosing (queued ->
  // printing, the realistic way a 409 happens at all -- see this hook's
  // own docstring) -- clearing on EVERY phase change (the 1st round's fix)
  // over-corrected, wiping the message within ~1s of it landing, sometimes
  // before it could be read. Clear only on `submit()` (handled directly
  // below) and once the job reaches a TERMINAL state, where a stale "your
  // cancel didn't land" note next to a fresh done/failed outcome would
  // just be confusing.
  useEffect(() => {
    if (phase === "done" || phase === "failed") {
      setCancelError(null);
    }
  }, [phase]);

  function submit(body: PrintRequest, printedCount: number) {
    if (mutation.isPending || active) return;
    setJobId(null);
    setErrorText(null);
    setCancelError(null);
    setProgress(null);
    setSubmittedCount(printedCount);
    submittedBodyKeyRef.current = bodyKey;
    setPhase("idle");
    mutation.mutate(body);
  }

  function cancel() {
    if (!jobId || phase !== "queued" || cancelMutation.isPending) return;
    cancelMutation.mutate(jobId);
  }

  return {
    phase,
    jobId,
    progress,
    errorText,
    submittedCount,
    printedBodyStale,
    canCancel: phase === "queued",
    isCanceling: cancelMutation.isPending,
    cancelError,
    isSubmitting: mutation.isPending,
    submit,
    cancel,
  };
}
