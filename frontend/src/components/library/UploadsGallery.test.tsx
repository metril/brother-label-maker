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
});
