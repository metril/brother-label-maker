import { afterEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { History } from "./History";
import { useDesignerStore } from "../stores/designer";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";
import { mockWebSocketInstances } from "../test/setup";

const INITIAL_DESIGNER_STATE = useDesignerStore.getState();

afterEach(() => {
  useDesignerStore.setState(INITIAL_DESIGNER_STATE, true);
});

function item(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "job-1",
    created_at: "2026-07-27T11:55:00.000000Z",
    status: "done",
    error: null,
    label_count: 3,
    chain_mode: "chain_ff",
    strategy: "classic",
    tape_width_mm: 24,
    tape_used_mm: 123.4,
    thumbnail_url: "/api/history/job-1/thumbnail",
    ...overrides,
  };
}

// The status/page-size filter <select>s render their OWN "Done"/"Failed"/
// "20"/"50"/... options unconditionally, from the very first render --
// before any fetch resolves. Every row-content assertion below is scoped
// `within(table)` (never a bare `screen.getByText(...)`) so it can never
// accidentally match one of those static option labels instead of the
// actual row; `findByRole("table")` is also this suite's own "the real
// data has loaded" signal, since the table only renders once
// `data.items.length > 0` (pages/History.tsx never renders one in the
// pending/empty states).
async function findTable() {
  return screen.findByRole("table");
}

describe("History page", () => {
  it("shows the empty state when there's nothing printed yet", async () => {
    server.use(http.get("/api/history", () => HttpResponse.json({ items: [], page: 1, page_size: 20, total: 0 })));
    renderWithProviders(<History />);

    expect(await screen.findByText("Nothing printed yet.")).toBeInTheDocument();
  });

  it("renders rows with thumbnail/status/mono values", async () => {
    server.use(http.get("/api/history", () => HttpResponse.json({ items: [item()], page: 1, page_size: 20, total: 1 })));
    renderWithProviders(<History />);

    const table = await findTable();
    expect(within(table).getByText("Done")).toBeInTheDocument();
    expect(within(table).getByText("3")).toBeInTheDocument();
    expect(within(table).getByText("24mm")).toBeInTheDocument();
    expect(within(table).getByText("123.4 mm")).toBeInTheDocument();
    expect(within(table).getByAltText("")).toHaveAttribute("src", "/api/history/job-1/thumbnail");
  });

  // Feed & cut design doc (2026-08-04): a feed_cut job has no real label
  // content (label_count: 0) and a Mode column that must show the row's
  // real identity ("Feed & cut"), not its always-"cut_each" chain_mode
  // (which would otherwise read as an ordinary one-label print) -- see
  // HistoryRow.tsx's own doc on this.
  it("a feed_cut job's row shows the humanized 'Feed & cut' label and renders sanely with no label content", async () => {
    server.use(
      http.get("/api/history", () =>
        HttpResponse.json({
          items: [
            item({
              kind: "feed_cut",
              label_count: 0,
              chain_mode: "cut_each",
              thumbnail_url: null,
              tape_used_mm: 24.5,
            }),
          ],
          page: 1,
          page_size: 20,
          total: 1,
        }),
      ),
    );
    renderWithProviders(<History />);

    const table = await findTable();
    const row = within(table).getByText("Feed & cut").closest("tr")!;
    expect(within(row).getByText("Done")).toBeInTheDocument();
    expect(within(row).getByText("0")).toBeInTheDocument();
    expect(within(row).getByText("24mm")).toBeInTheDocument();
    expect(within(row).getByText("24.5 mm")).toBeInTheDocument();
    // No chain-mode text ("Cut each") leaks through for a feed_cut row.
    expect(within(row).queryByText("Cut each")).not.toBeInTheDocument();
  });

  it("shows the failure text for a failed job", async () => {
    server.use(
      http.get("/api/history", () =>
        HttpResponse.json({ items: [item({ status: "failed", error: "printer out of tape" })], page: 1, page_size: 20, total: 1 }),
      ),
    );
    renderWithProviders(<History />);

    const table = await findTable();
    expect(within(table).getByText("Failed")).toBeInTheDocument();
    expect(within(table).getByText("printer out of tape")).toBeInTheDocument();
  });

  it("status/search filters and page size drive GET /api/history's own query params, within bounds", async () => {
    const user = userEvent.setup();
    const seenQueries: URLSearchParams[] = [];
    server.use(
      http.get("/api/history", ({ request }) => {
        seenQueries.push(new URL(request.url).searchParams);
        return HttpResponse.json({ items: [item()], page: 1, page_size: 20, total: 1 });
      }),
    );
    renderWithProviders(<History />);
    await findTable();

    await user.selectOptions(screen.getByLabelText("Status"), "failed");
    await waitFor(() => expect(seenQueries.at(-1)?.get("status")).toBe("failed"));

    await user.type(screen.getByLabelText("Search"), "uplink");
    await waitFor(() => expect(seenQueries.at(-1)?.get("q")).toBe("uplink"));

    await user.selectOptions(screen.getByLabelText("Per page"), "50");
    await waitFor(() => expect(seenQueries.at(-1)?.get("page_size")).toBe("50"));

    // Only ever the fixed, in-bounds options (1..100 per the backend's own
    // page_size validation) ever reach the request.
    for (const q of seenQueries) {
      const pageSize = Number(q.get("page_size") ?? "20");
      expect(pageSize).toBeGreaterThanOrEqual(1);
      expect(pageSize).toBeLessThanOrEqual(100);
      expect(Number(q.get("page") ?? "1")).toBeGreaterThanOrEqual(1);
    }
  });

  it("pagination controls respect the total/page_size bounds", async () => {
    const user = userEvent.setup();
    const seenPages: string[] = [];
    server.use(
      http.get("/api/history", ({ request }) => {
        const page = new URL(request.url).searchParams.get("page") ?? "1";
        seenPages.push(page);
        return HttpResponse.json({ items: [item()], page: Number(page), page_size: 20, total: 25 });
      }),
    );
    renderWithProviders(<History />);
    await findTable();

    expect(screen.getByText("Page 1 of 2 · 25 jobs")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(seenPages.at(-1)).toBe("2"));
    expect(await screen.findByRole("button", { name: "Next page" })).toBeDisabled();
  });

  it("Reprint POSTs and surfaces the new job's live status via WS", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/history", () => HttpResponse.json({ items: [item()], page: 1, page_size: 20, total: 1 })),
      http.post("/api/history/job-1/reprint", () => HttpResponse.json({ job_id: "job-2" }, { status: 202 })),
    );
    renderWithProviders(<History />);
    const table = await findTable();

    await user.click(within(table).getByRole("button", { name: "Reprint job job-1" }));
    await waitFor(() => expect(within(table).getByText("Queued")).toBeInTheDocument());

    await waitFor(() => expect(mockWebSocketInstances.length).toBeGreaterThan(0));
    const socket = mockWebSocketInstances.at(-1)!;
    act(() => socket.emit({ event: "job.started", job_id: "job-2" }));
    await waitFor(() => expect(within(table).getByText("Printing")).toBeInTheDocument());
  });

  // Review fix-up: reprint had two real backend failure modes (404 -- the
  // job was deleted out-of-band; 409 -- a stored definition that no longer
  // validates, router_history.py's reprint_job docstring) that used to be
  // completely silent -- no role="alert", no chip, nothing visibly wrong.
  it("Reprint failure surfaces a readable role=alert message inline, not silently", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/history", () => HttpResponse.json({ items: [item()], page: 1, page_size: 20, total: 1 })),
      http.post("/api/history/job-1/reprint", () => HttpResponse.json({ detail: "job not found" }, { status: 404 })),
    );
    renderWithProviders(<History />);
    const table = await findTable();

    await user.click(within(table).getByRole("button", { name: "Reprint job job-1" }));
    expect(await within(table).findByRole("alert")).toHaveTextContent("job not found");
    // No status chip is added for a reprint that never actually got a job id.
    expect(within(table).queryByText("Queued")).not.toBeInTheDocument();
  });

  // The SECOND real backend failure mode -- router_history.py's own
  // reprint_job docstring: a stored definition that no longer validates
  // (e.g. a font/image it referenced was since removed) is a SERVER-side
  // resource having gone stale, hence 409 (not 422/404) -- was never
  // covered by a test on its own (only the 404 case above was).
  it("Reprint 409 (a stale stored definition) also surfaces a readable role=alert message", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/history", () => HttpResponse.json({ items: [item()], page: 1, page_size: 20, total: 1 })),
      http.post("/api/history/job-1/reprint", () =>
        HttpResponse.json({ detail: "font 'Deleted Font' is no longer available" }, { status: 409 }),
      ),
    );
    renderWithProviders(<History />);
    const table = await findTable();

    await user.click(within(table).getByRole("button", { name: "Reprint job job-1" }));
    expect(await within(table).findByRole("alert")).toHaveTextContent("font 'Deleted Font' is no longer available");
    expect(within(table).queryByText("Queued")).not.toBeInTheDocument();
  });

  // Review fix-up: History row actions used to share the exact same
  // accessible name ("Reprint"/"Details"/"Delete") across every row --
  // indistinguishable to a screen-reader user tabbing through the table.
  // Mirrors the "Move item N up" convention components/TrayItemRow.tsx
  // already established for a repeated-row list.
  it("gives each row's actions a distinct, row-identifying accessible name", async () => {
    server.use(
      http.get("/api/history", () =>
        HttpResponse.json({
          items: [item({ id: "job-1" }), item({ id: "job-2", created_at: "2026-07-27T10:00:00.000000Z" })],
          page: 1,
          page_size: 20,
          total: 2,
        }),
      ),
    );
    renderWithProviders(<History />);
    const table = await findTable();

    expect(within(table).getByRole("button", { name: "Reprint job job-1" })).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "Reprint job job-2" })).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "View details for job job-1" })).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "View details for job job-2" })).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "Delete job job-1" })).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "Delete job job-2" })).toBeInTheDocument();
  });

  // Task 4.3 fix-up: the distinct name used to be `job ${index + 1}` -- the
  // row's position on the CURRENT page, not the job itself. Re-fetching the
  // SAME two jobs in the opposite order (a filter change, a live-status
  // invalidation, anything that re-renders the table with a new sort) used
  // to silently swap which job "Reprint job 1" pointed at. Now that the name
  // is keyed off `item.id`, it must follow its own job across that reorder,
  // not stay pinned to a table position.
  it("keeps each row's accessible name pinned to its own job id across a re-sort, not to table position", async () => {
    let order: "asc" | "desc" = "asc";
    server.use(
      http.get("/api/history", () =>
        HttpResponse.json({
          items:
            order === "asc"
              ? [item({ id: "job-1" }), item({ id: "job-2" })]
              : [item({ id: "job-2" }), item({ id: "job-1" })],
          page: 1,
          page_size: 20,
          total: 2,
        }),
      ),
    );
    renderWithProviders(<History />);
    const table = await findTable();
    expect(await within(table).findByRole("button", { name: "Delete job job-1" })).toBeInTheDocument();

    order = "desc";
    // Same query key (status filter) re-triggers the same GET -- easiest
    // deterministic way to force a refetch without waiting on a real WS
    // event: toggling the status filter and back invalidates nothing
    // itself, but changing pageSize does trigger a fresh fetch under this
    // page's own query-key shape (see useHistory.ts).
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Per page"), "50");

    await waitFor(() => {
      const rows = within(table).getAllByRole("row").slice(1); // skip the header row
      expect(within(rows[0]!).getByRole("button", { name: "Delete job job-2" })).toBeInTheDocument();
      expect(within(rows[1]!).getByRole("button", { name: "Delete job job-1" })).toBeInTheDocument();
    });
  });

  it("Details shows the job's full definition and offers Load into designer for a single label", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/history", () => HttpResponse.json({ items: [item()], page: 1, page_size: 20, total: 1 })),
      http.get("/api/history/job-1", () =>
        HttpResponse.json({
          id: "job-1",
          created_at: "2026-07-27T11:55:00.000000Z",
          status: "done",
          error: null,
          definition: { labels: [{ type: "text", tape: { width_mm: 24, family: "tze" }, params: { lines: ["FROM HISTORY"] } }], options: {} },
          label_count: 1,
          chain_mode: "cut_each",
          strategy: "classic",
          tape_width_mm: 24,
          media_raw_byte: null,
          tape_used_mm: 40,
          thumbnail_png_b64: null,
        }),
      ),
    );
    renderWithProviders(<History />, { route: "/history" });
    const table = await findTable();

    await user.click(within(table).getByRole("button", { name: "View details for job job-1" }));
    const dialog = await screen.findByRole("dialog", { name: "Job details" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(within(dialog).getByText(/FROM HISTORY/)).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Load into designer" }));
    await waitFor(() => {
      expect(useDesignerStore.getState().selectedType).toBe("text");
      expect(useDesignerStore.getState().paramsByType.text?.lines).toEqual(["FROM HISTORY"]);
    });
  });

  it("Delete asks for confirmation before DELETEing", async () => {
    const user = userEvent.setup();
    const deleteSpy = vi.fn();
    server.use(
      http.get("/api/history", () => HttpResponse.json({ items: [item()], page: 1, page_size: 20, total: 1 })),
      http.delete("/api/history/job-1", () => {
        deleteSpy();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderWithProviders(<History />);
    const table = await findTable();

    await user.click(within(table).getByRole("button", { name: "Delete job job-1" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(deleteSpy).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleteSpy).toHaveBeenCalledTimes(1));
  });

  // Review fix-up: `page` could end up stuck past the real last page (a
  // filter change, or a delete, narrowed `total` while the user was on a
  // later page) -- the table/pager used to vanish entirely (gated on
  // `data.items.length`) and show the misleading "Nothing printed yet.",
  // stranding the user with no way back. The page now self-corrects.
  it("auto-clamps page back into range instead of stranding the user when the current page empties out", async () => {
    const user = userEvent.setup();
    let call = 0;
    server.use(
      http.get("/api/history", ({ request }) => {
        call += 1;
        const page = new URL(request.url).searchParams.get("page");
        if (call === 1) {
          // Initial load: page 1 of 2 (25 total @ page_size 20).
          return HttpResponse.json({ items: [item()], page: 1, page_size: 20, total: 25 });
        }
        if (page === "2") {
          // Landed on page 2, but everything shrank to 5 total (1 page)
          // between the first and second fetch -- page 2 no longer exists.
          return HttpResponse.json({ items: [], page: 2, page_size: 20, total: 5 });
        }
        // The clamp effect refetches page 1 -- real rows are there.
        return HttpResponse.json({ items: [item({ id: "job-2" })], page: 1, page_size: 20, total: 5 });
      }),
    );
    renderWithProviders(<History />);
    await findTable();

    await user.click(screen.getByRole("button", { name: "Next page" }));

    await waitFor(() => expect(screen.getByText("Page 1 of 1 · 5 jobs")).toBeInTheDocument());
    expect(screen.queryByText("Nothing printed yet.")).not.toBeInTheDocument();
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Done")).toBeInTheDocument();
  });

  it("a WS terminal event on a listed job updates its row status in place, then invalidates the list", async () => {
    let fetchCount = 0;
    server.use(
      http.get("/api/history", () => {
        fetchCount += 1;
        return HttpResponse.json({ items: [item({ status: "printing" })], page: 1, page_size: 20, total: 1 });
      }),
    );
    renderWithProviders(<History />);
    const table = await findTable();
    await waitFor(() => expect(within(table).getByText("Printing")).toBeInTheDocument());
    expect(fetchCount).toBe(1);

    await waitFor(() => expect(mockWebSocketInstances.length).toBeGreaterThan(0));
    const socket = mockWebSocketInstances.at(-1)!;
    act(() => socket.emit({ event: "job.done", job_id: "job-1" }));

    // The row updates immediately from the WS overlay, before any refetch
    // could possibly have completed.
    await waitFor(() => expect(within(table).getByText("Done")).toBeInTheDocument());
    // ... and the terminal event also invalidates the query so the real
    // row (fresh tape_used_mm/thumbnail) eventually replaces the overlay.
    await waitFor(() => expect(fetchCount).toBeGreaterThan(1));
  });
});
