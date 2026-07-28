import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Gallery } from "./Gallery";
import { useDesignerStore } from "../stores/designer";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";

const INITIAL_DESIGNER_STATE = useDesignerStore.getState();

afterEach(() => {
  useDesignerStore.setState(INITIAL_DESIGNER_STATE, true);
  vi.restoreAllMocks();
});

function galleryItem(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "text-hello",
    title: "Simple text",
    blurb: "A single line of text — the baseline label.",
    type: "text",
    tape: { width_mm: 24, family: "tze" },
    params: { lines: ["HELLO"] },
    length_mm: 45.2,
    png_b64: "iVBORw0KGgo=",
    min_feed_mm: 24.5,
    warnings: [],
    total_labels: null,
    sequence_value: null,
    ...overrides,
  };
}

describe("Gallery page", () => {
  it("renders a card per item with title, blurb, meta line, strip, and warning chips", async () => {
    server.use(
      http.get("/api/gallery", () =>
        HttpResponse.json([
          galleryItem(),
          galleryItem({
            id: "barcode-qr-url",
            title: "QR code, URL (caption dropped)",
            blurb: "Watch for the warning chip.",
            type: "barcode",
            length_mm: 19.6,
            warnings: [
              { code: "caption_omitted", severity: "warning", message: "caption omitted: too wide", object_id: null },
              { code: "short_label", severity: "info", message: "this label is 19.6mm long", object_id: null },
            ],
            total_labels: 4,
          }),
        ]),
      ),
    );
    renderWithProviders(<Gallery />, { route: "/gallery" });

    expect(await screen.findByText("Simple text")).toBeInTheDocument();
    expect(screen.getByText("A single line of text — the baseline label.")).toBeInTheDocument();
    expect(screen.getByText("45.2 mm")).toBeInTheDocument();
    // Both cards render a DeckStrip once /api/tapes resolves.
    await waitFor(() => expect(screen.getAllByTestId("printable-band")).toHaveLength(2));
    // Warning + info chips from the second card, and its serialized-run note.
    expect(screen.getByText("caption omitted: too wide")).toBeInTheDocument();
    expect(screen.getByText("this label is 19.6mm long")).toBeInTheDocument();
    expect(screen.getByText("label 1 of 4")).toBeInTheDocument();
  });

  it("Open in designer sets the type/params/tape in the store", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/gallery", () => HttpResponse.json([galleryItem({ params: { lines: ["FROM GALLERY"] } })])),
    );
    renderWithProviders(<Gallery />, { route: "/gallery" });

    await user.click(await screen.findByRole("button", { name: "Open in designer" }));

    await waitFor(() => {
      expect(useDesignerStore.getState().selectedType).toBe("text");
      expect(useDesignerStore.getState().paramsByType.text?.lines).toEqual(["FROM GALLERY"]);
      expect(useDesignerStore.getState().tape).toEqual({ width_mm: 24, family: "tze" });
    });
  });

  it("shows the error state when GET /api/gallery fails", async () => {
    // Silence the expected fetch-failure noise react-query logs on retry-less errors.
    vi.spyOn(console, "error").mockImplementation(() => {});
    server.use(http.get("/api/gallery", () => HttpResponse.json({ detail: "boom" }, { status: 500 })));
    renderWithProviders(<Gallery />, { route: "/gallery" });

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the gallery.");
  });
});
