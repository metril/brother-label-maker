import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, deleteHistoryJob, postHistoryReprint } from "../api/client";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { HistoryDetailsDialog } from "../components/HistoryDetailsDialog";
import { HistoryRow } from "../components/HistoryRow";
import { Pending } from "../components/ui/Pending";
import { Select, TextInput } from "../components/ui/inputs";
import { errorText, eyebrow, fieldLabelText, iconButtonClass, panel, typeHeading } from "../components/ui/styles";
import { useDialogController } from "../hooks/useDialogController";
import { useHistoryList } from "../hooks/useHistory";
import { useJobEventsContext } from "../hooks/useJobEvents";
import { isTerminalEventType } from "../lib/jobStatus";
import type { HistoryItem, JobStatus } from "../api/types";

const SEARCH_DEBOUNCE_MS = 300;
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];
const STATUS_OPTIONS: { value: JobStatus | ""; label: string }[] = [
  { value: "", label: "All statuses" },
  { value: "queued", label: "Queued" },
  { value: "printing", label: "Printing" },
  { value: "done", label: "Done" },
  { value: "failed", label: "Failed" },
  { value: "canceled", label: "Canceled" },
];

/** The History page (task 2.13): every print job, newest first, server-
 * paginated (GET /api/history's own page/page_size -- kept within the
 * backend's 1..100 page_size bound and page>=1 by construction: the
 * page-size control only offers values in that range, and Prev/Next stay
 * disabled at the bounds rather than ever stepping outside them). */
export function History() {
  const queryClient = useQueryClient();
  const { events } = useJobEventsContext();

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [status, setStatus] = useState<JobStatus | "">("");
  const [rawQuery, setRawQuery] = useState("");
  const [q, setQ] = useState("");

  useEffect(() => {
    const handle = setTimeout(() => {
      setQ(rawQuery);
      setPage(1);
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [rawQuery]);

  const { data, isPending, isError } = useHistoryList({ page, pageSize, status: status || undefined, q: q || undefined });

  const [reprintJobIds, setReprintJobIds] = useState<Record<string, string>>({});
  const reprintMutation = useMutation({
    mutationFn: (id: string) => postHistoryReprint(id),
    onSuccess: (result, id) => setReprintJobIds((prev) => ({ ...prev, [id]: result.job_id })),
  });

  const [deleteTarget, setDeleteTarget] = useState<HistoryItem | null>(null);
  const deleteDialog = useDialogController();
  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteHistoryJob(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["history"] });
      deleteDialog.close();
      setDeleteTarget(null);
    },
  });

  const [detailsId, setDetailsId] = useState<string | null>(null);
  const detailsDialog = useDialogController();

  // task 2.13: live WS updates for rows already on screen (status chip,
  // byte progress -- see HistoryRow.tsx) without waiting on a refetch.
  // Once a TRACKED job (a currently-listed row, or a just-triggered
  // reprint's new job) reaches a terminal event, the history query is
  // invalidated exactly once per job id -- `processedTerminalRef` is what
  // makes this "once": without it, every render where the event is still
  // present in `events` (i.e. forever, useJobEvents never forgets one)
  // would re-invalidate on every unrelated re-render.
  const processedTerminalRef = useRef(new Set<string>());
  useEffect(() => {
    const trackedIds = new Set<string>();
    for (const item of data?.items ?? []) trackedIds.add(item.id);
    for (const jobId of Object.values(reprintJobIds)) trackedIds.add(jobId);

    let shouldInvalidate = false;
    for (const [jobId, event] of Object.entries(events)) {
      if (!trackedIds.has(jobId)) continue;
      if (isTerminalEventType(event.event) && !processedTerminalRef.current.has(jobId)) {
        processedTerminalRef.current.add(jobId);
        shouldInvalidate = true;
      }
    }
    if (shouldInvalidate) {
      queryClient.invalidateQueries({ queryKey: ["history"] });
    }
  }, [events, data, reprintJobIds, queryClient]);

  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const isFiltered = q !== "" || status !== "";

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <h1 className={typeHeading}>History</h1>

      <div className={panel}>
        <div className="mb-4 flex flex-wrap items-end gap-3">
          <div className="min-w-[180px] flex-1">
            <label htmlFor="history-search" className={`${fieldLabelText} mb-1 block`}>
              Search
            </label>
            <TextInput id="history-search" value={rawQuery} onChange={setRawQuery} placeholder="Search job contents…" />
          </div>
          <div>
            <label htmlFor="history-status" className={`${fieldLabelText} mb-1 block`}>
              Status
            </label>
            <Select
              id="history-status"
              value={status}
              onChange={(v) => {
                setStatus(v as JobStatus | "");
                setPage(1);
              }}
              options={STATUS_OPTIONS}
            />
          </div>
          <div>
            <label htmlFor="history-page-size" className={`${fieldLabelText} mb-1 block`}>
              Per page
            </label>
            <Select
              id="history-page-size"
              value={String(pageSize)}
              onChange={(v) => {
                setPageSize(Number(v));
                setPage(1);
              }}
              options={PAGE_SIZE_OPTIONS.map((n) => ({ value: String(n), label: String(n) }))}
            />
          </div>
        </div>

        {isPending ? (
          <Pending />
        ) : isError || !data ? (
          <p role="alert" className={errorText}>
            Could not load print history.
          </p>
        ) : data.items.length === 0 ? (
          <p className="text-[13px] text-deck-400">{isFiltered ? "No jobs match these filters." : "Nothing printed yet."}</p>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] border-collapse text-left">
                <thead>
                  <tr className={`${eyebrow} border-b border-deck-800`}>
                    <th scope="col" className="py-2 pr-3 font-normal">
                      Preview
                    </th>
                    <th scope="col" className="py-2 pr-3 font-normal">
                      Printed
                    </th>
                    <th scope="col" className="py-2 pr-3 font-normal">
                      Status
                    </th>
                    <th scope="col" className="py-2 pr-3 font-normal">
                      Labels
                    </th>
                    <th scope="col" className="py-2 pr-3 font-normal">
                      Chain
                    </th>
                    <th scope="col" className="py-2 pr-3 font-normal">
                      Tape
                    </th>
                    <th scope="col" className="py-2 pr-3 font-normal">
                      Used
                    </th>
                    <th scope="col" className="py-2 pr-3 font-normal">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item) => (
                    <HistoryRow
                      key={item.id}
                      item={item}
                      liveEvent={events[item.id]}
                      reprintJobId={reprintJobIds[item.id] ?? null}
                      reprintEvent={reprintJobIds[item.id] ? events[reprintJobIds[item.id]!] : undefined}
                      reprintPending={reprintMutation.isPending && reprintMutation.variables === item.id}
                      onReprint={() => reprintMutation.mutate(item.id)}
                      onDetails={() => {
                        setDetailsId(item.id);
                        detailsDialog.open();
                      }}
                      onDelete={() => {
                        setDeleteTarget(item);
                        deleteDialog.open();
                      }}
                    />
                  ))}
                </tbody>
              </table>
            </div>

            <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
              <p className="font-mono text-[12px] text-deck-400">
                Page {data.page} of {totalPages} · {data.total} job{data.total === 1 ? "" : "s"}
              </p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className={iconButtonClass}
                  aria-label="Previous page"
                >
                  ‹
                </button>
                <button
                  type="button"
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className={iconButtonClass}
                  aria-label="Next page"
                >
                  ›
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      <ConfirmDialog
        open={deleteDialog.isOpen}
        onClose={() => {
          deleteDialog.close();
          setDeleteTarget(null);
        }}
        closeButtonRef={deleteDialog.closeButtonRef}
        label={deleteTarget ? `Delete job ${deleteTarget.id}?` : "Delete job?"}
        message="Delete this print job from history? This can't be undone."
        confirmLabel="Delete"
        isPending={deleteMutation.isPending}
        error={deleteMutation.isError ? (deleteMutation.error instanceof ApiError ? deleteMutation.error.message : "delete failed") : null}
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
      />

      <HistoryDetailsDialog
        jobId={detailsId}
        open={detailsDialog.isOpen}
        onClose={() => {
          detailsDialog.close();
          setDetailsId(null);
        }}
        closeButtonRef={detailsDialog.closeButtonRef}
      />
    </div>
  );
}
