import { afterEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { TrayPanel, type CurrentDesign } from "./TrayPanel";
import { usePrintPreviewStore } from "../stores/printPreview";
import { useTrayStore } from "../stores/tray";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";
import { mockWebSocketInstances } from "../test/setup";
import type { LabelDefinition, PrintEstimateResponse } from "../api/types";

const INITIAL_TRAY_STATE = useTrayStore.getState();

afterEach(() => {
  useTrayStore.setState(INITIAL_TRAY_STATE, true);
  usePrintPreviewStore.setState({ open: false });
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

/** components/GlobalTrayDrawer.tsx always passes `current={null}` (there's
 * no "current, unsaved design" away from the Designer page) -- these cover
 * the one shape GlobalTrayDrawer's own tests can't reach directly, since
 * that component hides itself entirely whenever the tray is empty (so a
 * `current === null` + empty-tray render never happens THROUGH it). Every
 * other `current === null` behavior (non-empty tray, printing, previews) is
 * already covered end-to-end via GlobalTrayDrawer.test.tsx. */
describe("TrayPanel -- current === null (away from the Designer page)", () => {
  it("an empty tray with no current design has nothing to print: Print is disabled, no crash, no serialization branch", async () => {
    server.use(http.post("/api/print/estimate", () => {
      throw new Error("must not be called: nothing renderable to estimate");
    }));

    renderWithProviders(<TrayPanel current={null} />);

    expect(await screen.findByText(/Nothing queued/)).toBeInTheDocument();
    expect(screen.getByText("Add content to estimate tape usage.")).toBeInTheDocument();
    // No "+ Add to tray" affordance either -- there's no current design to add.
    expect(screen.queryByRole("button", { name: "+ Add to tray" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Print 0 labels" })).toBeDisabled();
    // Track C2: nothing (renderable) to chain-preview either -- same gate
    // as the estimate panel/Print button above.
    expect(screen.getByRole("button", { name: "Preview" })).toBeDisabled();
  });
});

/** Track C2 rework: components/PrintPreviewDeck.tsx no longer renders
 * through TrayPanel at all -- it's mounted once, at AppShell level, and
 * reads its own content straight off stores/tray.ts (see that component's
 * own docstring). TrayPanel's own responsibility for "Preview" is
 * now just the button: disabled gating, and wiring stores/printPreview.ts
 * + the optional `closeTrayDrawer` prop -- the deck's actual content
 * (PNG/segments/stats/mode tabs/zoom/focus/Escape) is covered end-to-end
 * by PrintPreviewDeck.test.tsx instead. */
describe("TrayPanel -- Preview button", () => {
  it("is disabled when the tray has nothing valid to print (mirrors the estimate/Print gate)", () => {
    renderWithProviders(<TrayPanel current={currentDesign({ canSubmit: false })} />);
    expect(screen.getByRole("button", { name: "Preview" })).toBeDisabled();
  });

  // PrintPreviewDeck.tsx dropped its own current-design fallback (task:
  // "Print preview vs. FeedDeck" split) -- it previews the QUEUED JOB only,
  // so "Preview" must stay disabled with an empty tray even though a
  // current design would happily satisfy canEstimate/Print's OWN fallback.
  it("is disabled with an empty tray even though a current design exists (Preview previews the queue only)", () => {
    renderWithProviders(<TrayPanel current={currentDesign()} onAddToTray={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Preview" })).toBeDisabled();
    // The empty-tray Print/estimate fallback itself is unaffected.
    expect(screen.getByRole("button", { name: "Print 1 label" })).toBeEnabled();
  });

  it("is enabled once the tray has items, and opens the shared drawer store without touching the tray's own chainMode", async () => {
    const user = userEvent.setup();
    seedTrayItems(1);
    renderWithProviders(<TrayPanel current={currentDesign()} onAddToTray={vi.fn()} />);
    const previewButton = screen.getByRole("button", { name: "Preview" });
    expect(previewButton).toBeEnabled();
    expect(usePrintPreviewStore.getState().open).toBe(false);

    await user.click(previewButton);

    expect(usePrintPreviewStore.getState().open).toBe(true);
    // Opening the drawer does not touch the tray's own chainMode.
    expect(useTrayStore.getState().chainMode).toBe(INITIAL_TRAY_STATE.chainMode);
  });

  it("calls the optional closeTrayDrawer prop (GlobalTrayDrawer's own dialog.close) before opening the chain-preview drawer", async () => {
    const user = userEvent.setup();
    const closeTrayDrawer = vi.fn();
    seedTrayItems(1);
    renderWithProviders(
      <TrayPanel current={currentDesign()} onAddToTray={vi.fn()} closeTrayDrawer={closeTrayDrawer} />,
    );

    await user.click(screen.getByRole("button", { name: "Preview" }));

    expect(closeTrayDrawer).toHaveBeenCalledTimes(1);
    expect(usePrintPreviewStore.getState().open).toBe(true);
  });
});

// The tests below moved here verbatim (component swapped JobTray -> this
// component) from the now-deleted components/JobTray.test.tsx as part of
// unifying the Designer page's tray into components/GlobalTrayDrawer.tsx --
// they exercise TrayPanel's own content (estimate, chain mode, print/WS
// progress), which never depended on JobTray's sidebar/sheet shell around
// it in the first place.

describe("TrayPanel -- chain mode picker changes the estimate and shows the delta vs cut_each", () => {
  it('switching to Chain shows "saves X mm" using a SEPARATE cut_each baseline request', async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/print/estimate", async ({ request }) => {
        const body = (await request.json()) as { options?: { chain_mode?: string } };
        const total = body.options?.chain_mode === "chain_ff" ? 37.5 : 100;
        return HttpResponse.json(estimateBody({ total_mm: total, per_label_mm: total }));
      }),
    );

    renderWithProviders(<TrayPanel current={currentDesign()} onAddToTray={vi.fn()} />);
    // data-testid, not text: "Per label" is numerically IDENTICAL to the
    // total for a one-label body (see TrayPanel.tsx's own comment on
    // estimate-total-mm), so an exact-text query would be ambiguous even
    // scoped to the panel.
    const totalReadout = await screen.findByTestId("estimate-total-mm");

    await waitFor(() => expect(totalReadout).toHaveTextContent("100.0 mm"));

    await user.click(screen.getByRole("radio", { name: "Cut at end" }));

    await waitFor(() => expect(totalReadout).toHaveTextContent("37.5 mm"));
    expect(await screen.findByText("saves 62.5 mm vs cut each")).toBeInTheDocument();
  });
});

describe("TrayPanel -- estimate panel", () => {
  it("renders total_mm, per-label, notes, and a usage bar proportional to content/overhead", async () => {
    server.use(
      http.post("/api/print/estimate", () =>
        HttpResponse.json(
          estimateBody({ total_mm: 40, content_mm: 30, feed_overhead_mm: 10, per_label_mm: 22, notes: ["a leader allowance applies"] }),
        ),
      ),
    );

    renderWithProviders(<TrayPanel current={currentDesign()} onAddToTray={vi.fn()} />);

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
      <TrayPanel
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

describe("TrayPanel -- progress reaches done via the WS stream", () => {
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

    renderWithProviders(<TrayPanel current={currentDesign()} onAddToTray={vi.fn()} />);
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
// integration test drives the real store + real TrayPanel to pin the
// (now-corrected) shape of that behavior: print a 2-item tray, mutate it
// AFTER the job finishes, and confirm the success line keeps its ORIGINAL
// (frozen) count while the button recovers its live, count-bearing label.
describe("TrayPanel -- done-state freeze and reset (review fix-up)", () => {
  it("keeps the success line at its frozen count and returns Print to a live count-bearing label once the tray changes post-print", async () => {
    const user = userEvent.setup();
    seedTrayItems(2);
    server.use(
      http.post("/api/print/estimate", () => HttpResponse.json(estimateBody({ label_count: 2 }))),
      http.post("/api/print", () => HttpResponse.json({ job_id: "job-freeze" }, { status: 202 })),
    );

    renderWithProviders(<TrayPanel current={currentDesign()} onAddToTray={vi.fn()} />);
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

    renderWithProviders(<TrayPanel current={currentDesign()} onAddToTray={vi.fn()} />);
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

    renderWithProviders(<TrayPanel current={currentDesign()} onAddToTray={vi.fn()} />);
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
