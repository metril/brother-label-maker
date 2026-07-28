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

  it("moves focus into the sheet (the close button) on open, and restores focus to the trigger on close", async () => {
    const user = userEvent.setup();
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())));

    renderWithProviders(<JobTray current={currentDesign()} onAddToTray={vi.fn()} />);

    const bar = await screen.findByTestId("job-tray-mobile-bar");
    await user.click(bar);

    const closeButton = screen.getByRole("button", { name: "Close job tray" });
    await waitFor(() => expect(closeButton).toHaveFocus());

    const panel = screen.getByTestId("job-tray-panel");
    expect(panel).toHaveAttribute("role", "dialog");
    expect(panel).toHaveAttribute("aria-modal", "true");

    await user.click(closeButton);
    await waitFor(() => expect(bar).toHaveFocus());
  });
});

// Review fix-up (reported live): the done-state success line used to be
// re-derived from LIVE props every render instead of freezing what was
// actually printed, AND `phase` stayed "done" (and the button "Print
// again") forever once reached, regardless of later tray edits. Both bugs
// share one root cause (hooks/usePrintJob.ts had no notion of "the body
// that was actually submitted" at all) and are fixed together there.
//
// 2nd round: the 1st round's fix for the SECOND bug (reverting `phase`
// itself to "idle" the instant the body diverged) turned out to swallow
// the completion notice entirely for a body edited WHILE STILL PRINTING
// (the "done" transition and the "idle" revert landed in the same commit).
// The fix now keeps `phase` truthfully "done" -- and its frozen success
// line VISIBLE -- regardless of when the tray changed; only the BUTTON's
// own "Print again" label is suppressed once the body is stale. This
// integration test drives the real store + real JobTray to pin the
// (now-corrected) shape of that behavior: print a 2-item tray, mutate it
// AFTER the job finishes, and confirm the success line keeps its ORIGINAL
// (frozen) count while the button recovers its live, count-bearing label.
describe("JobTray -- done-state freeze and reset (review fix-up)", () => {
  it("keeps the success line at its frozen count and returns Print to a live count-bearing label once the tray changes post-print", async () => {
    const user = userEvent.setup();
    seedTrayItems(2);
    server.use(
      http.post("/api/print/estimate", () => HttpResponse.json(estimateBody({ label_count: 2 }))),
      http.post("/api/print", () => HttpResponse.json({ job_id: "job-freeze" }, { status: 202 })),
    );

    renderWithProviders(<JobTray current={currentDesign()} onAddToTray={vi.fn()} />);
    const printButton = await screen.findByRole("button", { name: "Print 2 labels (tray)" });
    await user.click(printButton);

    // The default poll handler (test/msw/handlers.ts) reports "done"
    // immediately -- no WS frame needed to reach the state under test.
    expect(await screen.findByText("Printed 2 labels.")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Print again" })).toBeInTheDocument();

    // Mutate the tray AFTER the print finished: duplicate item 1, now 3.
    await user.click(screen.getByRole("button", { name: "Duplicate item 1" }));

    // The success line must never be silently rewritten to describe the
    // NEW (3-item) tray -- "3" must never appear there -- but it also must
    // NOT disappear: the job genuinely printed 2 labels, and that
    // confirmation stays exactly as it was.
    expect(screen.queryByText(/Printed 3 labels/)).not.toBeInTheDocument();
    expect(screen.getByText("Printed 2 labels.")).toBeInTheDocument();

    // The BUTTON, meanwhile, gives the live, count-bearing label back --
    // not "Print again" persisting forever regardless of what the tray now
    // is (clicking it now would print the NEW, 3-item tray, not "again").
    expect(await screen.findByRole("button", { name: "Print 3 labels (tray)" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Print again" })).not.toBeInTheDocument();
  });

  // The exact regression the 2nd fix-up round closed: editing the tray
  // WHILE a job is still printing (not yet done) must not prevent the
  // success line from ever appearing once it finishes.
  it("a tray edit made WHILE still printing does not swallow the completion notice once job.done arrives", async () => {
    const user = userEvent.setup();
    seedTrayItems(2);
    server.use(
      http.post("/api/print/estimate", () => HttpResponse.json(estimateBody({ label_count: 2 }))),
      http.post("/api/print", () => HttpResponse.json({ job_id: "job-mid-edit" }, { status: 202 })),
      // Keep the poll fallback reporting "printing" (not "done") so the WS
      // frame below is what actually resolves this -- and so there's a
      // real window, while genuinely "printing", to edit the tray in.
      http.get("/api/print/jobs/:jobId", () =>
        HttpResponse.json({
          id: "job-mid-edit",
          created_at: "2026-07-27T00:00:00.000000Z",
          status: "printing",
          error: null,
          definition: {},
          label_count: 2,
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
    const printButton = await screen.findByRole("button", { name: "Print 2 labels (tray)" });
    await user.click(printButton);

    await waitFor(() => expect(mockWebSocketInstances.length).toBeGreaterThan(0));
    const socket = mockWebSocketInstances.at(-1)!;
    act(() => socket.emit({ event: "job.started", job_id: "job-mid-edit" }));
    await screen.findByRole("button", { name: "Printing…" });

    // Edit the tray WHILE the job is still actively printing.
    await user.click(screen.getByRole("button", { name: "Duplicate item 1" }));
    expect(screen.getByRole("button", { name: "Printing…" })).toBeInTheDocument();

    act(() => socket.emit({ event: "job.done", job_id: "job-mid-edit" }));

    // The completion notice must land -- with the count that ACTUALLY
    // printed (2), not the now-3-item tray -- and the button must recover
    // its live label rather than claiming "Print again".
    expect(await screen.findByText("Printed 2 labels.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Print 3 labels (tray)" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Print again" })).not.toBeInTheDocument();
  });

  it("a failed print is unaffected: the tray stays intact and the error/retry state doesn't reset just because the tray is edited", async () => {
    const user = userEvent.setup();
    seedTrayItems(1);
    server.use(
      http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())),
      http.post("/api/print", () => HttpResponse.json({ job_id: "job-fail" }, { status: 202 })),
      http.get("/api/print/jobs/:jobId", () =>
        HttpResponse.json({
          id: "job-fail",
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

    renderWithProviders(<JobTray current={currentDesign()} onAddToTray={vi.fn()} />);
    const printButton = await screen.findByRole("button", { name: "Print 1 label (tray)" });
    await user.click(printButton);

    expect(await screen.findByText("printer out of tape")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Duplicate item 1" }));

    // failed was never part of the bug this fixes -- editing the tray
    // (still 2 items now) must not clear the error, and Print keeps
    // reflecting the LIVE count the way it always did outside "done".
    expect(screen.getByText("printer out of tape")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Print 2 labels (tray)" })).toBeInTheDocument();
  });
});
