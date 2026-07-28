import { describe, expect, it } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { http, HttpResponse } from "msw";
import { usePrintJob } from "./usePrintJob";
import { JobEventsProvider } from "./useJobEvents";
import { server } from "../test/msw/server";
import { mockWebSocketInstances } from "../test/setup";
import type { PrintRequest } from "../api/types";

function createWrapper() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <JobEventsProvider>{children}</JobEventsProvider>
      </QueryClientProvider>
    );
  };
}

const BODY: PrintRequest = {
  labels: [{ type: "text", tape: { width_mm: 24, family: "tze" }, params: { lines: ["A"] } }],
  options: { chain_mode: "cut_each", margin_mm: 2, auto_cut: true },
};

async function latestSocket() {
  await waitFor(() => expect(mockWebSocketInstances.length).toBeGreaterThan(0));
  return mockWebSocketInstances.at(-1)!;
}

/** The default `/api/print/jobs/:id` handler (test/msw/handlers.ts) always
 * reports "done" -- fine for tests that WANT the poll fallback to resolve
 * quickly, but every test here that means to observe an intermediate
 * "queued"/"printing" state (or drive it via WS instead) must override it,
 * or the poll fallback's own default "done" response races ahead of --
 * and wins against -- whatever this test is actually trying to observe. */
function stillQueuedHandler(jobId: string) {
  return http.get("/api/print/jobs/:jobId", () =>
    HttpResponse.json({
      id: jobId,
      created_at: "2026-07-27T00:00:00.000000Z",
      status: "queued",
      error: null,
      definition: {},
      label_count: 1,
      chain_mode: "cut_each",
      strategy: null,
      tape_width_mm: 24,
      media_raw_byte: null,
      tape_used_mm: null,
      thumbnail_png_b64: null,
    }),
  );
}

describe("usePrintJob", () => {
  it("submit POSTs the body and moves to queued once the job id comes back", async () => {
    let capturedBody: unknown;
    server.use(
      http.post("/api/print", async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json({ job_id: "job-1" }, { status: 202 });
      }),
      stillQueuedHandler("job-1"),
    );

    const { result } = renderHook(() => usePrintJob(), { wrapper: createWrapper() });

    act(() => result.current.submit(BODY));

    await waitFor(() => expect(result.current.phase).toBe("queued"));
    expect(result.current.jobId).toBe("job-1");
    expect(capturedBody).toEqual(BODY);
    expect(result.current.canCancel).toBe(true);
  });

  it("job.started then job.progress over the WS stream move phase to printing and update the progress bytes", async () => {
    server.use(
      http.post("/api/print", () => HttpResponse.json({ job_id: "job-2" }, { status: 202 })),
      stillQueuedHandler("job-2"),
    );

    const { result } = renderHook(() => usePrintJob(), { wrapper: createWrapper() });
    act(() => result.current.submit(BODY));
    await waitFor(() => expect(result.current.jobId).toBe("job-2"));

    const socket = await latestSocket();
    act(() => socket.emit({ event: "job.started", job_id: "job-2" }));
    await waitFor(() => expect(result.current.phase).toBe("printing"));
    expect(result.current.canCancel).toBe(false);

    act(() => socket.emit({ event: "job.progress", job_id: "job-2", sent: 512, total: 2048 }));
    await waitFor(() => expect(result.current.progress).toEqual({ sent: 512, total: 2048 }));
  });

  it("job.done over the WS stream resolves phase to done (no polling needed)", async () => {
    server.use(
      http.post("/api/print", () => HttpResponse.json({ job_id: "job-3" }, { status: 202 })),
      // Deliberately never reports a terminal status -- if this passes, the
      // "done" state came from the WS frame, not from polling.
      http.get("/api/print/jobs/:jobId", () =>
        HttpResponse.json({
          id: "job-3",
          created_at: "2026-07-27T00:00:00.000000Z",
          status: "printing",
          error: null,
          definition: {},
          label_count: 1,
          chain_mode: "cut_each",
          strategy: null,
          tape_width_mm: 24,
          media_raw_byte: null,
          tape_used_mm: null,
          thumbnail_png_b64: null,
        }),
      ),
    );

    const { result } = renderHook(() => usePrintJob(), { wrapper: createWrapper() });
    act(() => result.current.submit(BODY));
    await waitFor(() => expect(result.current.jobId).toBe("job-3"));

    const socket = await latestSocket();
    act(() => socket.emit({ event: "job.done", job_id: "job-3" }));

    await waitFor(() => expect(result.current.phase).toBe("done"));
  });

  it("falls back to polling GET /api/print/jobs/:id when no WS frame ever arrives", async () => {
    server.use(
      http.post("/api/print", () => HttpResponse.json({ job_id: "job-4" }, { status: 202 })),
      http.get("/api/print/jobs/:jobId", () =>
        HttpResponse.json({
          id: "job-4",
          created_at: "2026-07-27T00:00:00.000000Z",
          status: "failed",
          error: "printer out of tape",
          definition: {},
          label_count: 1,
          chain_mode: "cut_each",
          strategy: null,
          tape_width_mm: 24,
          media_raw_byte: null,
          tape_used_mm: null,
          thumbnail_png_b64: null,
        }),
      ),
    );

    const { result } = renderHook(() => usePrintJob(), { wrapper: createWrapper() });
    act(() => result.current.submit(BODY));

    await waitFor(() => expect(result.current.phase).toBe("failed"), { timeout: 3000 });
    expect(result.current.errorText).toBe("printer out of tape");
  });

  it("cancel() succeeds (200) while queued, setting a canceled terminal state", async () => {
    server.use(
      http.post("/api/print", () => HttpResponse.json({ job_id: "job-5" }, { status: 202 })),
      http.post("/api/print/jobs/:jobId/cancel", () => HttpResponse.json({ status: "canceled" })),
      stillQueuedHandler("job-5"),
    );

    const { result } = renderHook(() => usePrintJob(), { wrapper: createWrapper() });
    act(() => result.current.submit(BODY));
    await waitFor(() => expect(result.current.canCancel).toBe(true));

    act(() => result.current.cancel());

    await waitFor(() => expect(result.current.phase).toBe("failed"));
    expect(result.current.errorText).toBe("print job was canceled");
    expect(result.current.cancelError).toBeNull();
  });

  // The CAS contract's own race (router_print.py's cancel_print_job): the
  // worker can dequeue a job (server-side status -> "printing") in the gap
  // between this UI last observing "queued" and its cancel request actually
  // landing -- canCancel/the hook's local `phase` is still "queued" at the
  // moment cancel() is called (no job.started/poll update has arrived yet),
  // but the SERVER now 409s. This is the realistic way a 409 happens at
  // all, since the hook's own cancel() no-ops locally once phase has
  // already flipped away from "queued".
  it("cancel() surfaces the server's 409 message inline when the job started printing just before the request landed", async () => {
    server.use(
      http.post("/api/print", () => HttpResponse.json({ job_id: "job-6" }, { status: 202 })),
      http.post("/api/print/jobs/:jobId/cancel", () =>
        HttpResponse.json({ detail: "cannot cancel job in status 'printing'" }, { status: 409 }),
      ),
      stillQueuedHandler("job-6"),
    );

    const { result } = renderHook(() => usePrintJob(), { wrapper: createWrapper() });
    act(() => result.current.submit(BODY));
    await waitFor(() => expect(result.current.canCancel).toBe(true));

    act(() => result.current.cancel());

    await waitFor(() => expect(result.current.cancelError).toBe("cannot cancel job in status 'printing'"));
    // A failed CANCEL doesn't mean the print itself failed -- the job's own
    // phase is untouched by a 409 (it keeps tracking via WS/poll normally).
    expect(result.current.phase).toBe("queued");
  });
});
