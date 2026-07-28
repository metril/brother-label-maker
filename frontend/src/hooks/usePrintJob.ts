import { useEffect, useState } from "react";
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
   * or the 30s watchdog timing out. */
  errorText: string | null;
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
   * print itself failed; deliberately not cleared by a fresh submit until
   * that submit's own cancelError-resetting `submit()` call clears it. */
  cancelError: string | null;
  isSubmitting: boolean;
  submit: (body: PrintRequest) => void;
  cancel: () => void;
}

/** The job tray's print-job lifecycle: POST /api/print, then track the job
 * to a terminal state two ways at once -- the shared WS event stream
 * (useJobEvent, live push) and a 1s poll of GET /api/print/jobs/{id} as a
 * fallback, whichever source reports a terminal status first wins -- plus
 * POST /api/print/jobs/{id}/cancel while the job is still queued. A REAL
 * timer (not query data) enforces a 30s cap from submission to a terminal
 * state, same reasoning as the original (pre-2.12) PrintButton.tsx: TanStack
 * Query's structural sharing keeps `data` reference-stable across polls
 * that return an unchanged payload, so a derivation effect keyed off
 * `pollQuery.data` itself would silently stop re-running for a job stuck
 * reporting the same status forever.
 *
 * Extracted out of PrintButton.tsx (task 2.9-2.11's single-label component)
 * so ONE hook call -- made once, in JobTray.tsx -- can back BOTH the
 * detail panel's print section and the mobile compact bar's own status
 * label without opening a second WS-tracked/polled job or risking the two
 * disagreeing about what's currently in flight. */
export function usePrintJob(): UsePrintJobResult {
  const [phase, setPhase] = useState<PrintJobPhase>("idle");
  const [jobId, setJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState<PrintJobProgress | null>(null);
  const [errorText, setErrorText] = useState<string | null>(null);
  const [cancelError, setCancelError] = useState<string | null>(null);

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

  // Hard 30s cap from submission to a terminal state -- a REAL timer,
  // deliberately independent of any query/WS data reference (see this
  // module's own docstring). Covers both the "queued" and "printing"
  // windows as one continuous budget rather than resetting at the queued
  // -> printing transition.
  useEffect(() => {
    if (!active) return;
    const timer = setTimeout(() => {
      setPhase("failed");
      setErrorText("timed out waiting for print status");
    }, POLL_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [active]);

  function submit(body: PrintRequest) {
    if (mutation.isPending || active) return;
    setJobId(null);
    setErrorText(null);
    setCancelError(null);
    setProgress(null);
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
    canCancel: phase === "queued",
    isCanceling: cancelMutation.isPending,
    cancelError,
    isSubmitting: mutation.isPending,
    submit,
    cancel,
  };
}
