import { afterEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { JobTray, type CurrentDesign } from "./JobTray";
import { useTrayStore } from "../stores/tray";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";
import { mockWebSocketInstances } from "../test/setup";
import type { LabelDefinition, PrintEstimateResponse } from "../api/types";

const INITIAL_TRAY_STATE = useTrayStore.getState();

afterEach(() => {
  useTrayStore.setState(INITIAL_TRAY_STATE, true);
});

function def(text: string): LabelDefinition {
  return { type: "text", tape: { width_mm: 24, family: "tze" }, params: { lines: [text] } };
}

function currentDesign(overrides: Partial<CurrentDesign> = {}): CurrentDesign {
  return {
    definition: def("CURRENT"),
    canSubmit: true,
    isRenderable: () => true,
    png: null,
    lengthMm: 25.4,
    label: "Text — CURRENT",
    serializationEnabled: false,
    serialization: null,
    totalLabels: null,
    serializationHasVisibleError: false,
    ...overrides,
  };
}

function estimateBody(overrides: Partial<PrintEstimateResponse> = {}): PrintEstimateResponse {
  return {
    label_count: 1,
    label_lengths_mm: [25.4],
    content_mm: 25.4,
    feed_overhead_mm: 10,
    total_mm: 35.4,
    per_label_mm: 35.4,
    notes: [],
    ...overrides,
  };
}

function seedTrayItems(n: number) {
  for (let i = 0; i < n; i++) {
    useTrayStore.getState().addItem({ definition: def(`ITEM-${i}`), png: null, lengthMm: 20 + i, label: `Text — ITEM-${i}` });
  }
}

describe("JobTray -- empty state and print body semantics", () => {
  it('shows the empty-state prompt and "Print 1 label" for the current design when the tray is empty', async () => {
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())));
    renderWithProviders(<JobTray current={currentDesign()} onAddToTray={vi.fn()} />);

    expect(await screen.findByText(/Nothing queued\. Design a label and add it to print several at once\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Print 1 label" })).toBeInTheDocument();
  });

  it("empty tray: Print POSTs a body whose `labels` is just the current design", async () => {
    const user = userEvent.setup();
    let capturedBody: { labels: LabelDefinition[] } | undefined;
    server.use(
      http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())),
      http.post("/api/print", async ({ request }) => {
        capturedBody = (await request.json()) as typeof capturedBody;
        return HttpResponse.json({ job_id: "job-1" }, { status: 202 });
      }),
    );

    renderWithProviders(<JobTray current={currentDesign()} onAddToTray={vi.fn()} />);
    const printButton = await screen.findByRole("button", { name: "Print 1 label" });
    await user.click(printButton);

    await waitFor(() => expect(capturedBody).toBeDefined());
    expect(capturedBody?.labels).toEqual([def("CURRENT")]);
  });

  it("non-empty tray: Print POSTs the tray's own items, NOT the current design", async () => {
    const user = userEvent.setup();
    seedTrayItems(2);
    let capturedBody: { labels: LabelDefinition[] } | undefined;
    server.use(
      http.post("/api/print/estimate", () => HttpResponse.json(estimateBody({ label_count: 2 }))),
      http.post("/api/print", async ({ request }) => {
        capturedBody = (await request.json()) as typeof capturedBody;
        return HttpResponse.json({ job_id: "job-2" }, { status: 202 });
      }),
    );

    renderWithProviders(<JobTray current={currentDesign()} onAddToTray={vi.fn()} />);
    const printButton = await screen.findByRole("button", { name: "Print 2 labels (tray)" });
    await user.click(printButton);

    await waitFor(() => expect(capturedBody).toBeDefined());
    expect(capturedBody?.labels).toEqual([def("ITEM-0"), def("ITEM-1")]);
  });

  it("serialization on + a non-empty tray blocks Print with a clear message instead of ever POSTing", async () => {
    const user = userEvent.setup();
    seedTrayItems(1);
    const printSpy = vi.fn();
    server.use(
      http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())),
      http.post("/api/print", () => {
        printSpy();
        return HttpResponse.json({ job_id: "job-x" }, { status: 202 });
      }),
    );

    renderWithProviders(
      <JobTray current={currentDesign({ serializationEnabled: true, serialization: { kind: "numeric", count: 5 }, totalLabels: 5 })} onAddToTray={vi.fn()} />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(/can't be combined/);
    const printButton = screen.getByRole("button", { name: "Print 1 label (tray)" });
    expect(printButton).toBeDisabled();

    await user.click(printButton);
    expect(printSpy).not.toHaveBeenCalled();
  });
});

describe("JobTray -- tray item add/reorder/duplicate/remove", () => {
  it("onAddToTray is wired to the + Add to tray button, and item controls (up/down/duplicate/remove) work through the real store", async () => {
    const user = userEvent.setup();
    const onAddToTray = vi.fn(() => {
      useTrayStore.getState().addItem({ definition: def("NEW"), png: null, lengthMm: 10, label: "Text — NEW" });
    });
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())));

    renderWithProviders(<JobTray current={currentDesign()} onAddToTray={onAddToTray} />);

    await user.click(await screen.findByRole("button", { name: "+ Add to tray" }));
    expect(onAddToTray).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("Text — NEW")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Duplicate item 1" }));
    expect(useTrayStore.getState().items).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: "Move item 2 up" }));
    await user.click(screen.getByRole("button", { name: "Remove item 1" }));
    expect(useTrayStore.getState().items).toHaveLength(1);
  });
});

describe("JobTray -- chain mode picker changes the estimate and shows the delta vs cut_each", () => {
  it('switching to Chain shows "saves X mm" using a SEPARATE cut_each baseline request', async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/print/estimate", async ({ request }) => {
        const body = (await request.json()) as { options?: { chain_mode?: string } };
        const total = body.options?.chain_mode === "chain_ff" ? 37.5 : 100;
        return HttpResponse.json(estimateBody({ total_mm: total, per_label_mm: total }));
      }),
    );

    renderWithProviders(<JobTray current={currentDesign()} onAddToTray={vi.fn()} />);
    // data-testid, not text: "Per label" is numerically IDENTICAL to the
    // total for a one-label body (see JobTray.tsx's own comment on
    // estimate-total-mm), so an exact-text query would be ambiguous even
    // scoped to the panel.
    const totalReadout = await screen.findByTestId("estimate-total-mm");

    await waitFor(() => expect(totalReadout).toHaveTextContent("100.0 mm"));

    await user.click(screen.getByRole("radio", { name: "Chain" }));

    await waitFor(() => expect(totalReadout).toHaveTextContent("37.5 mm"));
    expect(await screen.findByText("saves 62.5 mm vs cut each")).toBeInTheDocument();
  });
});

describe("JobTray -- estimate panel", () => {
  it("renders total_mm, per-label, notes, and a usage bar proportional to content/overhead", async () => {
    server.use(
      http.post("/api/print/estimate", () =>
        HttpResponse.json(
          estimateBody({ total_mm: 40, content_mm: 30, feed_overhead_mm: 10, per_label_mm: 22, notes: ["a leader allowance applies"] }),
        ),
      ),
    );

    renderWithProviders(<JobTray current={currentDesign()} onAddToTray={vi.fn()} />);

    await waitFor(() => expect(screen.getByTestId("estimate-total-mm")).toHaveTextContent("40.0 mm"));
    expect(screen.getByText("22.0 mm")).toBeInTheDocument(); // "Per label"
    expect(screen.getByText("· a leader allowance applies")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("estimate-usage-content")).toHaveStyle({ width: "75%" }));
    expect(screen.getByTestId("estimate-usage-overhead")).toHaveStyle({ width: "25%" });
  });

  // Carry-forward fix: a settled over-cap (or otherwise server-rejected)
  // serialization already shows its own error in the Serialize panel --
  // the tray must defer to it, not print the identical raw message again.
  it("defers to the Serialize panel's own error instead of duplicating the raw 422 text", async () => {
    server.use(http.post("/api/print/estimate", () => HttpResponse.json({ detail: "total labels 1500 exceeds the 1000 maximum" }, { status: 422 })));

    renderWithProviders(
      <JobTray
        current={currentDesign({
          serializationEnabled: true,
          serialization: { kind: "numeric", count: 500, copies_per_value: 3 },
          serializationHasVisibleError: true,
        })}
        onAddToTray={vi.fn()}
      />,
    );

    expect(await screen.findByText("Fix the serialization run in the Serialize panel to see a tape estimate.")).toBeInTheDocument();
    expect(screen.queryByText(/exceeds the 1000 maximum/)).not.toBeInTheDocument();
  });
});

describe("JobTray -- progress reaches done via the WS stream", () => {
  it("shows queued -> printing -> done, driven by job.started/job.progress/job.done", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())),
      http.post("/api/print", () => HttpResponse.json({ job_id: "job-progress" }, { status: 202 })),
      // The default poll handler (test/msw/handlers.ts) always reports
      // "done" -- override so the poll fallback doesn't race ahead of (and
      // win against) the WS-driven progression this test means to observe.
      http.get("/api/print/jobs/:jobId", () =>
        HttpResponse.json({
          id: "job-progress",
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
      ),
    );

    renderWithProviders(<JobTray current={currentDesign()} onAddToTray={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "Print 1 label" }));

    await waitFor(() => expect(mockWebSocketInstances.length).toBeGreaterThan(0));
    const socket = mockWebSocketInstances.at(-1)!;

    act(() => socket.emit({ event: "job.started", job_id: "job-progress" }));
    act(() => socket.emit({ event: "job.progress", job_id: "job-progress", sent: 100, total: 100 }));
    await waitFor(() => expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100"));

    act(() => socket.emit({ event: "job.done", job_id: "job-progress" }));
    expect(await screen.findByRole("button", { name: "Print again" })).toBeInTheDocument();
  });
});

describe("JobTray -- mobile compact bar", () => {
  it("renders a fixed bottom bar with the total_mm summary, hidden classes at lg:, and expands the same panel on tap", async () => {
    const user = userEvent.setup();
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody({ total_mm: 40 }))));

    renderWithProviders(<JobTray current={currentDesign()} onAddToTray={vi.fn()} />);

    const bar = await screen.findByTestId("job-tray-mobile-bar");
    expect(bar.className).toContain("lg:hidden");
    expect(bar.className).toContain("fixed");
    expect(bar.className).toContain("bottom-0");
    await waitFor(() => expect(within(bar).getByText("40.0 mm")).toBeInTheDocument());

    const panel = screen.getByTestId("job-tray-panel");
    expect(panel.className).toContain("translate-y-[120%]");

    await user.click(bar);
    expect(panel.className).toContain("translate-y-0");
    expect(panel.className).not.toContain("translate-y-[120%]");
  });
});
