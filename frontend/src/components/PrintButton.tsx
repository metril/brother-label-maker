import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ApiError, getPrintJob, postPrint } from "../api/client";
import { useJobEvent } from "../hooks/useJobEvents";
import type { LabelDefinition } from "../api/types";

const POLL_INTERVAL_MS = 1000;
const POLL_TIMEOUT_MS = 30_000;
const DONE_FLASH_MS = 2000;

type Phase = "idle" | "printing" | "done" | "failed";

interface PrintButtonProps {
  definition: LabelDefinition;
  disabled?: boolean;
}

/** POST /api/print, then track the job to a terminal state two ways at
 * once: the shared WS event stream (useJobEvent, live push) and a 1s poll
 * of GET /api/print/jobs/{id} as a fallback -- whichever source reports
 * "done"/"failed" first wins. A REAL timer (not query data) enforces the
 * 30s cap -- see its effect below for why. */
export function PrintButton({ definition, disabled }: PrintButtonProps) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [jobId, setJobId] = useState<string | null>(null);
  const [errorText, setErrorText] = useState<string | null>(null);
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const wsEvent = useJobEvent(jobId);
  const wsStatus = wsEvent?.event;
  const wsError = wsEvent?.error;

  const mutation = useMutation({
    mutationFn: (def: LabelDefinition) =>
      postPrint({
        labels: [def],
        options: { chain_mode: "cut_each", margin_mm: 2.0, auto_cut: true },
      }),
    onSuccess: (data) => {
      setJobId(data.job_id);
      setPhase("printing");
    },
    onError: (err) => {
      setPhase("failed");
      setErrorText(err instanceof ApiError ? err.message : "print request failed");
    },
  });

  const pollEnabled =
    phase === "printing" && jobId !== null && wsStatus !== "job.done" && wsStatus !== "job.failed";

  const pollQuery = useQuery({
    queryKey: ["print-job-poll", jobId],
    queryFn: () => getPrintJob(jobId as string),
    enabled: pollEnabled,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "done" || status === "failed" || status === "canceled" ? false : POLL_INTERVAL_MS;
    },
  });

  // Read out only the PRIMITIVE fields the derivation below cares about
  // (not `pollQuery.data` itself) -- TanStack Query's structural sharing
  // keeps `data` reference-STABLE across polls that return an equal
  // payload, so depending on the object would mean this effect silently
  // stops re-running the moment the server starts replying with the same
  // status every time (e.g. stuck "printing"). That was exactly the bug
  // that made the old 30s-timeout branch dead code -- see the timer effect
  // below for the actual fix to that (a real timer, independent of any
  // query/WS data reference at all).
  const polledStatus = pollQuery.data?.status;
  const polledError = pollQuery.data?.error;
  const pollErrorMessage = pollQuery.error
    ? pollQuery.error instanceof ApiError
      ? pollQuery.error.message
      : "failed to check print status"
    : null;

  useEffect(() => {
    if (phase !== "printing" || !jobId) return;

    if (wsStatus === "job.done") {
      setPhase("done");
    } else if (wsStatus === "job.failed") {
      setPhase("failed");
      setErrorText(wsError ?? "print job failed");
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
  }, [phase, jobId, wsStatus, wsError, polledStatus, polledError, pollErrorMessage]);

  // Hard 30s cap, driven by a REAL timer armed the moment we enter
  // "printing" -- deliberately NOT derived from query/WS data, so it fires
  // even when nothing ever changes at all (job wedged "queued"/"printing"
  // forever, or both the WS and poll paths silently going nowhere). Self-
  // cancels via the effect cleanup once `phase` leaves "printing" for any
  // other reason (the derivation effect above already resolved it first).
  useEffect(() => {
    if (phase !== "printing") return;
    const timer = setTimeout(() => {
      setPhase("failed");
      setErrorText("timed out waiting for print status");
    }, POLL_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [phase]);

  // Flash "done" briefly, then return to idle so the button is usable again.
  useEffect(() => {
    if (phase !== "done") return;
    flashTimerRef.current = setTimeout(() => {
      setPhase("idle");
      setJobId(null);
    }, DONE_FLASH_MS);
    return () => {
      if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
    };
  }, [phase]);

  const busy = phase === "printing" || mutation.isPending;

  function handleClick() {
    if (busy || disabled) return;
    // Clear the previous job's id/error BEFORE mutating -- otherwise a
    // re-click after a failure briefly re-reads the old job's terminal WS
    // event / poll data (still keyed on the old jobId) and flashes its
    // error again before the new job id ever arrives.
    setJobId(null);
    setErrorText(null);
    setPhase("printing");
    mutation.mutate(definition);
  }

  let label = "Print";
  if (mutation.isPending) label = "Sending…";
  else if (phase === "printing") label = "Printing…";
  else if (phase === "done") label = "Printed";

  const buttonClass =
    phase === "done"
      ? "border-emerald-500 bg-emerald-950 text-emerald-300"
      : phase === "failed"
        ? "border-red-600 bg-red-950 text-red-300"
        : "border-amber-500 bg-amber-600 text-ink-950 hover:bg-amber-500";

  return (
    <div className="flex flex-col items-start gap-2">
      <button
        type="button"
        onClick={handleClick}
        disabled={busy || disabled}
        className={`rounded-md border px-5 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${buttonClass}`}
      >
        {label}
      </button>
      {phase === "failed" && errorText && (
        <p role="alert" className="text-xs text-red-400">
          {errorText}
        </p>
      )}
    </div>
  );
}
