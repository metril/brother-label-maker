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

    await user.click(within(table).getByRole("button", { name: "Reprint" }));
    await waitFor(() => expect(within(table).getByText("Queued")).toBeInTheDocument());

    await waitFor(() => expect(mockWebSocketInstances.length).toBeGreaterThan(0));
    const socket = mockWebSocketInstances.at(-1)!;
    act(() => socket.emit({ event: "job.started", job_id: "job-2" }));
    await waitFor(() => expect(within(table).getByText("Printing")).toBeInTheDocument());
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

    await user.click(within(table).getByRole("button", { name: "Details" }));
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

    await user.click(within(table).getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(deleteSpy).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleteSpy).toHaveBeenCalledTimes(1));
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
