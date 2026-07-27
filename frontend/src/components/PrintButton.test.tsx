import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { PrintButton } from "./PrintButton";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";
import { mockWebSocketInstances } from "../test/setup";
import type { LabelDefinition, PrintJob } from "../api/types";

const DEFINITION: LabelDefinition = {
  type: "text",
  tape: { width_mm: 24, family: "tze" },
  params: {
    lines: ["HELLO"],
    font_family: "Inter",
    bold: false,
    font_size_px: null,
    h_align: "center",
    length_mm: null,
    padding_mm: 2,
  },
};

function job(overrides: Partial<PrintJob>): PrintJob {
  return {
    id: "job-1",
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
    preview_png: null,
    ...overrides,
  };
}

describe("PrintButton", () => {
  it("POSTs a print job whose body contains the current definition", async () => {
    const user = userEvent.setup();
    let capturedBody: unknown;
    server.use(
      http.post("/api/print", async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json({ job_id: "job-1" }, { status: 202 });
      }),
      http.get("/api/print/jobs/:jobId", () => HttpResponse.json(job({ status: "printing" }))),
    );

    renderWithProviders(<PrintButton definition={DEFINITION} />);
    await user.click(screen.getByRole("button", { name: "Print" }));

    await waitFor(() => expect(capturedBody).toBeDefined());
    expect(capturedBody).toEqual({
      labels: [DEFINITION],
      options: { chain_mode: "cut_each", margin_mm: 2, auto_cut: true },
    });
  });

  it("shows the success state once the job is polled as done", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/print", () => HttpResponse.json({ job_id: "job-done" }, { status: 202 })),
      http.get("/api/print/jobs/:jobId", () => HttpResponse.json(job({ id: "job-done", status: "done" }))),
    );

    renderWithProviders(<PrintButton definition={DEFINITION} />);
    await user.click(screen.getByRole("button", { name: "Print" }));

    await waitFor(() => expect(screen.getByRole("button")).toHaveTextContent("Printed"));
  });

  it("shows the job's error text inline when it fails", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/print", () => HttpResponse.json({ job_id: "job-failed" }, { status: 202 })),
      http.get("/api/print/jobs/:jobId", () =>
        HttpResponse.json(
          job({ id: "job-failed", status: "failed", error: "printer out of tape" }),
        ),
      ),
    );

    renderWithProviders(<PrintButton definition={DEFINITION} />);
    await user.click(screen.getByRole("button", { name: "Print" }));

    expect(await screen.findByText("printer out of tape")).toBeInTheDocument();
  });

  it("shows the success state when job.done arrives over the WS event stream (no polling)", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/print", () => HttpResponse.json({ job_id: "job-ws-done" }, { status: 202 })),
      // Poll handler deliberately never reports a terminal status itself --
      // if this test passes, the "done" state came from the WS frame below,
      // not from polling.
      http.get("/api/print/jobs/:jobId", () => HttpResponse.json(job({ id: "job-ws-done", status: "printing" }))),
    );

    renderWithProviders(<PrintButton definition={DEFINITION} />);
    await user.click(screen.getByRole("button", { name: "Print" }));

    await waitFor(() => expect(mockWebSocketInstances.length).toBeGreaterThan(0));
    const socket = mockWebSocketInstances.at(-1)!;

    act(() => {
      socket.emit({ event: "job.done", job_id: "job-ws-done" });
    });

    await waitFor(() => expect(screen.getByRole("button")).toHaveTextContent("Printed"));
  });

  it("shows the job's error text when job.failed arrives over the WS event stream (no polling)", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/print", () => HttpResponse.json({ job_id: "job-ws-failed" }, { status: 202 })),
      http.get("/api/print/jobs/:jobId", () => HttpResponse.json(job({ id: "job-ws-failed", status: "printing" }))),
    );

    renderWithProviders(<PrintButton definition={DEFINITION} />);
    await user.click(screen.getByRole("button", { name: "Print" }));

    await waitFor(() => expect(mockWebSocketInstances.length).toBeGreaterThan(0));
    const socket = mockWebSocketInstances.at(-1)!;

    act(() => {
      socket.emit({ event: "job.failed", job_id: "job-ws-failed", error: "printer jammed" });
    });

    expect(await screen.findByText("printer jammed")).toBeInTheDocument();
  });

  it("times out after 30s when the job never resolves, even when the polled status never changes", async () => {
    // Regression test for a bug where the button wedged in "Printing…"
    // forever: the old terminal-state effect depended on `pollQuery.data`
    // itself, and TanStack Query's structural sharing keeps `data`
    // reference-stable across polls that return an identical payload -- so
    // an unchanging "printing" status (this handler, deliberately) never
    // re-triggered the effect that was supposed to catch a timeout. The
    // fix drives the 30s cap from a real timer instead, armed independently
    // of any query data.
    server.use(
      http.post("/api/print", () => HttpResponse.json({ job_id: "job-stuck" }, { status: 202 })),
      http.get("/api/print/jobs/:jobId", () => HttpResponse.json(job({ id: "job-stuck", status: "printing" }))),
    );

    vi.useFakeTimers();
    try {
      renderWithProviders(<PrintButton definition={DEFINITION} />);
      fireEvent.click(screen.getByRole("button", { name: "Print" }));

      // Advance in 1s steps (not one 31s jump) so ~30 real polls actually
      // get served the identical "printing" payload -- a single big jump
      // only advances render count enough to coincidentally trip a
      // dead-branch check on the mutation's own late render, without
      // genuinely exercising repeated polls against unchanging data.
      for (let i = 0; i < 35; i++) {
        await act(async () => {
          await vi.advanceTimersByTimeAsync(1000);
        });
      }

      expect(screen.getByRole("button")).toHaveTextContent("Print");
      expect(screen.getByText("timed out waiting for print status")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});
