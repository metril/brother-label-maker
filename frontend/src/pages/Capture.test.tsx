import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Route, Routes } from "react-router-dom";
import { Capture } from "./Capture";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";
import { defaultSettingsBody } from "../test/msw/handlers";

const item = {
  id: "item-1",
  name: "Impact Driver",
  description: "",
  asset_id: "000-123",
  archived: false,
  quantity: null,
  entity_type: "item",
  parent: null,
  tags: [],
  thumbnail_id: null,
  image_id: null,
};

function useHomebox(opts: { matches?: unknown[]; writes?: boolean; attach?: () => Response | Promise<Response> } = {}) {
  server.use(
    http.get("/api/settings", () =>
      HttpResponse.json({
        settings: defaultSettingsBody.settings.map((row) =>
          row.key === "homebox_writes_enabled" ? { ...row, value: opts.writes ?? true } : row,
        ),
      }),
    ),
    http.get("/api/homebox/settings", () =>
      HttpResponse.json({ qr_base_url: null, effective_qr_base_url: "http://hb.local" }),
    ),
    http.get("/api/homebox/assets/:assetId", () => HttpResponse.json(opts.matches ?? [item])),
    http.get("/api/homebox/entities/:id/path", () =>
      HttpResponse.json([
        { id: "loc", name: "Garage", type: "location" },
        { id: "item-1", name: "Impact Driver", type: "item" },
      ]),
    ),
    http.post("/api/homebox/entities/:id/attachments", async () =>
      opts.attach ? opts.attach() : HttpResponse.json({ entity_id: "item-1", attachment_id: "att-1", primary: true }),
    ),
  );
}

async function openItem(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Find item"), "123{Enter}");
  await screen.findByText("Impact Driver");
}

function takePhoto() {
  const input = screen.getByTestId("photo-input");
  fireEvent.change(input, { target: { files: [new File(["x"], "p.jpg", { type: "image/jpeg" })] } });
}

describe("Capture", () => {
  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => "blob:preview");
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => vi.restoreAllMocks());

  it("without camera support shows manual entry and a hint", () => {
    useHomebox();
    renderWithProviders(<Capture />, { route: "/capture" });
    expect(screen.getByLabelText("Find item")).toHaveAttribute("placeholder", "Asset # or item name");
    expect(screen.getByRole("button", { name: "Scan from photo" })).toBeInTheDocument();
    expect(screen.getByText(/needs camera access over HTTPS/)).toBeInTheDocument();
  });

  it("resolves a typed asset number, uploads a photo and returns to scanning", async () => {
    useHomebox();
    const user = userEvent.setup();
    renderWithProviders(<Capture />, { route: "/capture" });
    await openItem(user);
    expect(await screen.findByText("Garage")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: /Set as primary/ })).toHaveAttribute("aria-checked", "true");

    takePhoto();
    await user.click(await screen.findByRole("button", { name: "Upload" }));
    expect(await screen.findByText(/Saved to Impact Driver/)).toBeInTheDocument();
    expect(await screen.findByLabelText("Find item", undefined, { timeout: 3000 })).toBeInTheDocument();
  });

  it("shows Not found for zero matches", async () => {
    useHomebox({ matches: [] });
    const user = userEvent.setup();
    renderWithProviders(<Capture />, { route: "/capture" });
    await user.type(screen.getByLabelText("Find item"), "9{Enter}");
    expect(await screen.findByText(/Not found: asset 000-009/)).toBeInTheDocument();
  });

  it("maps a 403 upload to the Settings hint and keeps the photo for retry", async () => {
    useHomebox({ attach: () => HttpResponse.json({ detail: "writes disabled" }, { status: 403 }) });
    const user = userEvent.setup();
    renderWithProviders(<Capture />, { route: "/capture" });
    await openItem(user);
    takePhoto();
    await user.click(await screen.findByRole("button", { name: "Upload" }));
    expect(await screen.findByText("Enable HomeBox writes in Settings.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Upload" })).toBeInTheDocument());
  });

  it("disables Take photo with a Settings hint when HomeBox writes are off", async () => {
    useHomebox({ writes: false });
    const user = userEvent.setup();
    renderWithProviders(<Capture />, { route: "/capture" });
    await openItem(user);
    expect(await screen.findByRole("link", { name: "Open Settings" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Take photo" })).toBeDisabled();
  });

  it("links to sign-in on a 401 lookup", async () => {
    server.use(http.get("/api/homebox/assets/:assetId", () => HttpResponse.json({ detail: "no" }, { status: 401 })));
    const user = userEvent.setup();
    renderWithProviders(<Capture />, { route: "/capture" });
    await user.type(screen.getByLabelText("Find item"), "5{Enter}");
    expect(await screen.findByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/api/auth/login?next=/capture");
  });

  it("close button leaves the capture page", async () => {
    useHomebox();
    const user = userEvent.setup();
    renderWithProviders(
      <Routes>
        <Route path="/capture" element={<Capture />} />
        <Route path="/homebox" element={<p>Browse page</p>} />
      </Routes>,
      { route: "/capture" },
    );
    await user.click(screen.getByRole("button", { name: "Close capture" }));
    expect(await screen.findByText("Browse page")).toBeInTheDocument();
  });

  it("searches by item name and opens the chosen result", async () => {
    useHomebox();
    server.use(
      http.get("/api/homebox/entities", ({ request }) => {
        const q = new URL(request.url).searchParams.get("q");
        return HttpResponse.json({ items: q === "impact" ? [item] : [], page: 1, page_size: 20, total: q === "impact" ? 1 : 0 });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<Capture />, { route: "/capture" });
    await user.type(screen.getByLabelText("Find item"), "impact");
    await user.click(await screen.findByRole("button", { name: /Impact Driver/ }));
    expect(await screen.findByRole("switch", { name: /Set as primary/ })).toBeInTheDocument();
  });

  it("clears search text and results after scanning another", async () => {
    useHomebox();
    server.use(
      http.get("/api/homebox/entities", () => HttpResponse.json({ items: [item], page: 1, page_size: 20, total: 1 })),
    );
    const user = userEvent.setup();
    renderWithProviders(<Capture />, { route: "/capture" });
    await user.type(screen.getByLabelText("Find item"), "impact");
    await user.click(await screen.findByRole("button", { name: /Impact Driver/ }));
    await user.click(await screen.findByRole("button", { name: "Scan another" }));
    expect(screen.getByLabelText("Find item")).toHaveValue("");
    expect(screen.queryByRole("button", { name: /Impact Driver/ })).not.toBeInTheDocument();
  });
});
