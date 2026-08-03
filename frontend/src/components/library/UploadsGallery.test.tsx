import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { UploadsGallery } from "./UploadsGallery";
import { renderWithQueryClient } from "../../test/utils";
import { server } from "../../test/msw/server";

function item(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    image_id: "img-1",
    width: 64,
    height: 48,
    size_bytes: 2048,
    mtime: "2026-07-27T00:00:00.000000Z",
    ...overrides,
  };
}

describe("UploadsGallery", () => {
  it("shows the empty state when there are no uploads", async () => {
    server.use(http.get("/api/images", () => HttpResponse.json({ items: [], page: 1, page_size: 24, total: 0 })));
    renderWithQueryClient(<UploadsGallery />);

    expect(await screen.findByText(/No uploads yet/)).toBeInTheDocument();
  });

  it("renders a grid of uploaded thumbnails with dimensions/size captions", async () => {
    server.use(
      http.get("/api/images", () =>
        HttpResponse.json({
          items: [
            item({ image_id: "img-1", width: 64, height: 48, size_bytes: 2048 }),
            item({ image_id: "img-2", width: 100, height: 50, size_bytes: 1_500_000 }),
          ],
          page: 1,
          page_size: 24,
          total: 2,
        }),
      ),
      // H6: grid tiles must request the bounded THUMBNAIL route, never the
      // full-resolution original -- overridden here (not in the shared
      // handlers.ts) since no other suite needs this endpoint stubbed.
      http.get("/api/images/:id/thumb", () => new HttpResponse(new Uint8Array([1, 2, 3]), { status: 200 })),
    );
    renderWithQueryClient(<UploadsGallery />);

    expect(await screen.findByRole("img", { name: "Upload img-1" })).toHaveAttribute(
      "src",
      "/api/images/img-1/thumb",
    );
    expect(screen.getByRole("img", { name: "Upload img-2" })).toHaveAttribute(
      "src",
      "/api/images/img-2/thumb",
    );
    expect(screen.getByText("64×48 · 2.0 KB")).toBeInTheDocument();
    expect(screen.getByText("100×50 · 1.4 MB")).toBeInTheDocument();
    expect(screen.getByText("2 of 2 uploads")).toBeInTheDocument();
  });

  it("Load more appends the next page's items to the grid instead of replacing it", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/images", ({ request }) => {
        const url = new URL(request.url);
        const page = Number(url.searchParams.get("page") ?? "1");
        if (page === 1) {
          return HttpResponse.json({ items: [item({ image_id: "img-1" })], page: 1, page_size: 1, total: 2 });
        }
        return HttpResponse.json({ items: [item({ image_id: "img-2" })], page: 2, page_size: 1, total: 2 });
      }),
    );
    renderWithQueryClient(<UploadsGallery />);

    expect(await screen.findByRole("button", { name: "Delete upload img-1" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete upload img-2" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByRole("button", { name: "Delete upload img-2" })).toBeInTheDocument();
    // The first page's item is still there -- appended, not replaced.
    expect(screen.getByRole("button", { name: "Delete upload img-1" })).toBeInTheDocument();
    // Both pages loaded -- nothing left to load.
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("delete confirms via ConfirmDialog, calls DELETE, and refreshes the list", async () => {
    const user = userEvent.setup();
    let deleted = false;
    server.use(
      http.get("/api/images", () =>
        HttpResponse.json({
          items: deleted ? [] : [item({ image_id: "img-1" })],
          page: 1,
          page_size: 24,
          total: deleted ? 0 : 1,
        }),
      ),
      http.delete("/api/images/img-1", () => {
        deleted = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderWithQueryClient(<UploadsGallery />);

    await user.click(await screen.findByRole("button", { name: "Delete upload img-1" }));
    // ConfirmDialog's own confirm button -- default confirmLabel "Delete",
    // distinct accessible name from the per-item "Delete upload img-1" trigger.
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(screen.getByText(/No uploads yet/)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Delete upload img-1" })).not.toBeInTheDocument();
  });

  it("uploading a file invalidates the list so the new upload shows up", async () => {
    const user = userEvent.setup();
    let uploaded = false;
    server.use(
      http.post("/api/images", () => {
        uploaded = true;
        return HttpResponse.json({ image_id: "img-new", width: 10, height: 10 }, { status: 201 });
      }),
      http.get("/api/images", () =>
        HttpResponse.json({
          items: uploaded ? [item({ image_id: "img-new", width: 10, height: 10 })] : [],
          page: 1,
          page_size: 24,
          total: uploaded ? 1 : 0,
        }),
      ),
    );
    renderWithQueryClient(<UploadsGallery />);

    expect(await screen.findByText(/No uploads yet/)).toBeInTheDocument();

    const file = new File(["fake-bytes"], "logo.png", { type: "image/png" });
    await user.upload(screen.getByLabelText("Upload image"), file);

    await waitFor(() => expect(screen.getByRole("button", { name: "Delete upload img-new" })).toBeInTheDocument());
  });

  // L20 (docs/code-review-2026-08.md): the three failure branches below had
  // no coverage at all -- every existing test above is happy-path.

  it("upload failure shows the backend's own error detail via role=alert", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/images", () => HttpResponse.json({ items: [], page: 1, page_size: 24, total: 0 })),
      // A realistic 422 detail string (router_images.py's own shape) --
      // the ApiError unwrapping in client.ts must surface this VERBATIM,
      // not a generic fallback, since it's the user's only feedback on
      // exactly why their upload was rejected.
      http.post("/api/images", () =>
        HttpResponse.json(
          { detail: "image is 4000x4000 (16000000 px), exceeding the 8000000px cap" },
          { status: 422 },
        ),
      ),
    );
    renderWithQueryClient(<UploadsGallery />);
    await screen.findByText(/No uploads yet/);

    const file = new File(["fake-bytes"], "huge.png", { type: "image/png" });
    await user.upload(screen.getByLabelText("Upload image"), file);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "image is 4000x4000 (16000000 px), exceeding the 8000000px cap",
    );
  });

  it("list load failure shows 'Could not load uploads.'", async () => {
    server.use(
      http.get("/api/images", () => HttpResponse.json({ detail: "internal error" }, { status: 500 })),
    );
    renderWithQueryClient(<UploadsGallery />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load uploads.");
  });

  // M11 (docs/code-review-2026-08.md): the useInfiniteQuery migration fixed
  // a real corruption in the PREVIOUS hand-rolled page/appendedPageRef
  // component (see UploadsGallery.tsx's own module docstring), but nothing
  // in this file actually reproduced it -- every test above happens to pass
  // against the old component too. The bug needs an INACTIVE (already
  // loaded, but no longer the "current page") query to still be sitting in
  // react-query's cache holding pre-delete data when a later action
  // resurrects it -- which needs 3+ loaded pages (a 2-page repro doesn't
  // reproduce it: with only one page below the active one, the old
  // component's `resetAndInvalidate` collapses `items` straight back down
  // to a fresh page 1 and there's nothing stale left to resurface).
  it("M11 regression: deleting an image doesn't leave a stale/duplicate page from before the delete in the grid", async () => {
    const user = userEvent.setup();
    // 50 items -> 3 pages at this component's PAGE_SIZE (24): 24 + 24 + 2.
    // A real (mutable) source-of-truth array, not a canned per-test
    // response -- the GET handler slices it by the request's own
    // page/page_size, and DELETE actually removes from it, so a page
    // fetched AFTER the delete is genuinely different content from the
    // same page fetched BEFORE it (the shift that makes stale-cache
    // corruption visible as a real duplicate, not just a missing item).
    const dataset = Array.from({ length: 50 }, (_, i) => item({ image_id: `img-${i + 1}` }));
    server.use(
      http.get("/api/images", ({ request }) => {
        const url = new URL(request.url);
        const page = Number(url.searchParams.get("page") ?? "1");
        const pageSize = Number(url.searchParams.get("page_size") ?? "24");
        const start = (page - 1) * pageSize;
        return HttpResponse.json({
          items: dataset.slice(start, start + pageSize),
          page,
          page_size: pageSize,
          total: dataset.length,
        });
      }),
      http.delete("/api/images/:id", ({ params }) => {
        const idx = dataset.findIndex((d) => d.image_id === params.id);
        if (idx !== -1) dataset.splice(idx, 1);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderWithQueryClient(<UploadsGallery />);

    expect(await screen.findByRole("button", { name: "Delete upload img-1" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Load more" }));
    await screen.findByRole("button", { name: "Delete upload img-25" });
    await user.click(screen.getByRole("button", { name: "Load more" }));
    // All 50 loaded (3 pages) -- nothing left to load.
    await screen.findByRole("button", { name: "Delete upload img-49" });
    await waitFor(() => expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument());

    // Delete an image loaded as part of PAGE 1 -- img-25 (loaded via page
    // 2) and everything after it shifts down by one slot server-side once
    // this resolves.
    await user.click(screen.getByRole("button", { name: "Delete upload img-1" }));
    await user.click(await screen.findByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    // The old component's `resetAndInvalidate` resets its own `page` state
    // to 1, which -- since only the CURRENTLY ACTIVE page's query is
    // refetched by `invalidateQueries`'s default active-only behavior --
    // collapses `items` back down to a fresh (but page-1-only) slice and
    // re-shows "Load more". Clicking it re-subscribes to the SAME
    // `["images", 2]` cache entry from before the delete: react-query
    // serves that STALE (pre-delete) snapshot instantly while it
    // backgrounds a fresh refetch, the old component's `appendedPageRef`
    // guard already advances past 2 on the stale snapshot, and the fresh
    // refetch's result is then silently dropped -- the stale page-2 slice
    // (which now overlaps the boundary-shifted fresh page 1) is what
    // renders permanently. The fixed component has no such gap: every
    // loaded page lives under one `useInfiniteQuery` entry, so
    // `invalidateQueries` refetches all three at once and there's nothing
    // left to load here.
    const loadMoreAgain = screen.queryByRole("button", { name: "Load more" });
    if (loadMoreAgain) {
      await user.click(loadMoreAgain);
    }

    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Delete upload img-1" })).not.toBeInTheDocument();
    });
    const remainingIds = screen
      .getAllByRole("button", { name: /^Delete upload / })
      .map((button) => button.getAttribute("aria-label"));
    expect(new Set(remainingIds).size).toBe(remainingIds.length);
  });

  it("delete failure surfaces the error inside the ConfirmDialog, which stays open", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/images", () =>
        HttpResponse.json({ items: [item({ image_id: "img-1" })], page: 1, page_size: 24, total: 1 }),
      ),
      http.delete("/api/images/img-1", () =>
        HttpResponse.json({ detail: "cannot delete: referenced by an active label" }, { status: 500 }),
      ),
    );
    renderWithQueryClient(<UploadsGallery />);

    await user.click(await screen.findByRole("button", { name: "Delete upload img-1" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("cannot delete: referenced by an active label");
    // The dialog stays open (only a SUCCESSFUL delete closes it) and the
    // item is still there -- the failed delete never silently removed it.
    expect(dialog).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete upload img-1" })).toBeInTheDocument();
  });
});
