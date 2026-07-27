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
 * once: the shared WS event stream (useJobEvent, live push) and a
 * 1s poll of GET /api/print/jobs/{id} as a fallback (capped at 30s) --
 * whichever source reports "done"/"failed" first wins. See the task brief's
 * PrintButton doc: "tracks job via useJobEvents (fallback: poll ... every
 * 1s until terminal, max 30s)". */
export function PrintButton({ definition, disabled }: PrintButtonProps) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [jobId, setJobId] = useState<string | null>(null);
  const [errorText, setErrorText] = useState<string | null>(null);
  const startedAtRef = useRef<number>(0);
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const wsEvent = useJobEvent(jobId);

  const mutation = useMutation({
    mutationFn: (def: LabelDefinition) =>
      postPrint({
        labels: [def],
        options: { chain_mode: "cut_each", margin_mm: 2.0, auto_cut: true },
      }),
    onMutate: () => {
      setErrorText(null);
    },
    onSuccess: (data) => {
      setJobId(data.job_id);
      startedAtRef.current = Date.now();
      setPhase("printing");
    },
    onError: (err) => {
      setPhase("failed");
      setErrorText(err instanceof ApiError ? err.message : "print request failed");
    },
  });

  const resolvedByWs = wsEvent?.event === "job.done" || wsEvent?.event === "job.failed";
  const pollEnabled = phase === "printing" && jobId !== null && !resolvedByWs;

  const pollQuery = useQuery({
    queryKey: ["print-job-poll", jobId],
    queryFn: () => getPrintJob(jobId as string),
    enabled: pollEnabled,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "done" || status === "failed" || status === "canceled") return false;
      if (Date.now() - startedAtRef.current > POLL_TIMEOUT_MS) return false;
      return POLL_INTERVAL_MS;
    },
  });

  useEffect(() => {
    if (phase !== "printing" || !jobId) return;

    if (wsEvent?.event === "job.done") {
      setPhase("done");
      return;
    }
    if (wsEvent?.event === "job.failed") {
      setPhase("failed");
      setErrorText(wsEvent.error ?? "print job failed");
      return;
    }

    const polled = pollQuery.data;
    if (polled?.status === "done") {
      setPhase("done");
    } else if (polled?.status === "failed") {
      setPhase("failed");
      setErrorText(polled.error ?? "print job failed");
    } else if (polled?.status === "canceled") {
      setPhase("failed");
      setErrorText("print job was canceled");
    } else if (Date.now() - startedAtRef.current > POLL_TIMEOUT_MS) {
      setPhase("failed");
      setErrorText("timed out waiting for print status");
    }
  }, [phase, jobId, wsEvent, pollQuery.data]);

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
