import { afterEach, describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Homebox } from "./Homebox";
import { useDesignerStore } from "../stores/designer";
import { useTrayStore } from "../stores/tray";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";
import type { HomeboxEntitySummary } from "../api/types";

const INITIAL_DESIGNER_STATE = useDesignerStore.getState();
const INITIAL_TRAY_STATE = useTrayStore.getState();

afterEach(() => {
  useDesignerStore.setState(INITIAL_DESIGNER_STATE, true);
  useTrayStore.setState(INITIAL_TRAY_STATE, true);
});

function entitySummary(overrides: Partial<HomeboxEntitySummary> = {}): HomeboxEntitySummary {
  return {
    id: "e-1",
    name: "Impact Driver",
    description: "",
    asset_id: "000-001",
    archived: false,
    quantity: null,
    entity_type: { id: "et-1", name: "Tool", is_location: false },
    parent: null,
    tags: [],
    thumbnail_id: null,
    image_id: null,
    ...overrides,
  };
}

describe("Homebox page", () => {
  it("renders entities from the mocked entities endpoint", async () => {
    server.use(
      http.get("/api/homebox/entities", () =>
        HttpResponse.json({ items: [entitySummary()], page: 1, page_size: 50, total: 1 }),
      ),
    );
    renderWithProviders(<Homebox />, { route: "/homebox" });

    expect(await screen.findByText("Impact Driver")).toBeInTheDocument();
    expect(screen.getByText("000-001")).toBeInTheDocument();
  });

  it("clicking a location in the tree filters results by parent_id", async () => {
    const user = userEvent.setup();
    const seenParentIds: (string | null)[] = [];
    server.use(
      http.get("/api/homebox/entities/tree", () =>
        HttpResponse.json([{ id: "loc-1", name: "Garage", type: "location", children: [] }]),
      ),
      http.get("/api/homebox/entities", ({ request }) => {
        seenParentIds.push(new URL(request.url).searchParams.get("parent_id"));
        return HttpResponse.json({ items: [], page: 1, page_size: 50, total: 0 });
      }),
    );
    renderWithProviders(<Homebox />, { route: "/homebox" });

    await waitFor(() => expect(seenParentIds.length).toBeGreaterThan(0));
    await user.click(await screen.findByRole("button", { name: "Garage" }));

    await waitFor(() => expect(seenParentIds.at(-1)).toBe("loc-1"));
  });

  it("an asset-id-shaped search shows the Asset ID matches section with all disambiguation matches", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/homebox/assets/:assetId", () =>
        HttpResponse.json([
          entitySummary({ id: "e-1", name: "Impact Driver A" }),
          entitySummary({ id: "e-2", name: "Impact Driver B" }),
        ]),
      ),
    );
    renderWithProviders(<Homebox />, { route: "/homebox" });

    await user.type(await screen.findByLabelText("Search"), "000-001");

    expect(await screen.findByText("Asset ID matches")).toBeInTheDocument();
    expect(await screen.findByText("Impact Driver A")).toBeInTheDocument();
    expect(await screen.findByText("Impact Driver B")).toBeInTheDocument();
  });

  it("selecting two entities and adding to tray builds correct LabelDefinitions (breadcrumb, qr_data, tape)", async () => {
    const user = userEvent.setup();
    useDesignerStore.setState({ tape: { width_mm: 24, family: "tze" } });
    server.use(
      http.get("/api/homebox/entities", () =>
        HttpResponse.json({
          items: [
            entitySummary({ id: "e-1", name: "Impact Driver", asset_id: "000-001" }),
            entitySummary({
              id: "e-2",
              name: "Shelf B",
              asset_id: "",
              entity_type: { id: "et-2", name: "Location", is_location: true },
            }),
          ],
          page: 1,
          page_size: 50,
          total: 2,
        }),
      ),
      http.get("/api/homebox/entities/:id/path", ({ params }) => {
        if (params.id === "e-1") {
          return HttpResponse.json([
            { id: "loc-1", name: "Garage", type: "location" },
            { id: "e-1", name: "Impact Driver", type: "item" },
          ]);
        }
        return HttpResponse.json([
          { id: "loc-1", name: "Garage", type: "location" },
          { id: "e-2", name: "Shelf B", type: "location" },
        ]);
      }),
      http.get("/api/homebox/settings", () =>
        HttpResponse.json({ qr_base_url: null, effective_qr_base_url: "https://homebox.example.com" }),
      ),
    );
    renderWithProviders(<Homebox />, { route: "/homebox" });

    await user.click(await screen.findByLabelText("Select Impact Driver"));
    await user.click(screen.getByLabelText("Select Shelf B"));
    await user.click(await screen.findByRole("button", { name: "Add 2 to tray" }));

    await waitFor(() => expect(useTrayStore.getState().items).toHaveLength(2));
    const [assetItem, locationItem] = useTrayStore.getState().items;

    expect(assetItem!.definition).toEqual({
      type: "homebox_asset",
      tape: { width_mm: 24, family: "tze" },
      params: {
        asset_id: "000-001",
        name: "Impact Driver",
        location: "Garage",
        qr_data: "https://homebox.example.com/a/000-001",
        show_qr: true,
      },
    });
    expect(locationItem!.definition).toEqual({
      type: "homebox_location",
      tape: { width_mm: 24, family: "tze" },
      params: {
        name: "Shelf B",
        path: "Garage",
        qr_data: "https://homebox.example.com/location/e-2",
        show_qr: true,
      },
    });
    expect(await screen.findByText("Added 2 labels to tray")).toBeInTheDocument();
  });

  it("renders a setup hint (the env vars needed) when HomeBox isn't configured", async () => {
    server.use(
      http.get("/api/homebox/status", () =>
        HttpResponse.json({ configured: false, reachable: null, healthy: null, version: null, error: null }),
      ),
    );
    renderWithProviders(<Homebox />, { route: "/homebox" });

    expect(await screen.findByText("HOMEBOX_URL")).toBeInTheDocument();
    expect(screen.getByText("HOMEBOX_API_KEY")).toBeInTheDocument();
  });

  it("shows the status error prominently when HomeBox is configured but unreachable", async () => {
    server.use(
      http.get("/api/homebox/status", () =>
        HttpResponse.json({
          configured: true,
          reachable: false,
          healthy: null,
          version: null,
          error: "HomeBox rejected the API key (HTTP 401) -- check HOMEBOX_API_KEY",
        }),
      ),
    );
    renderWithProviders(<Homebox />, { route: "/homebox" });

    expect(await screen.findByRole("alert")).toHaveTextContent("HomeBox rejected the API key (HTTP 401)");
  });

  it("shows a readable error (the detail text) when GET /api/homebox/entities 502s", async () => {
    server.use(
      http.get("/api/homebox/entities", () =>
        HttpResponse.json({ detail: "HomeBox server error (HTTP 503)" }, { status: 502 }),
      ),
    );
    renderWithProviders(<Homebox />, { route: "/homebox" });

    expect(await screen.findByRole("alert")).toHaveTextContent("HomeBox server error (HTTP 503)");
  });

  it("shows the bulk-create panel only when homebox_writes_enabled is on", async () => {
    server.use(
      http.get("/api/homebox/entities", () => HttpResponse.json({ items: [], page: 1, page_size: 50, total: 0 })),
    );
    const { unmount } = renderWithProviders(<Homebox />, { route: "/homebox" });
    await screen.findByText("No entities to show.");
    expect(screen.queryByRole("heading", { name: /Bulk create/ })).not.toBeInTheDocument();
    unmount();

    server.use(
      http.get("/api/homebox/tags", () => HttpResponse.json([])),
      http.get("/api/settings", () =>
        HttpResponse.json({
          settings: [{ key: "homebox_writes_enabled", value: true, source: "db", editable: true }],
        }),
      ),
    );
    renderWithProviders(<Homebox />, { route: "/homebox" });
    expect(await screen.findByRole("heading", { name: /Bulk create/ })).toBeInTheDocument();
  });

  it("a row's cable label type builds a cable_wrap definition when added to the tray", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/homebox/entities", () =>
        HttpResponse.json({ items: [entitySummary()], page: 1, page_size: 50, total: 1 }),
      ),
      http.get("/api/homebox/settings", () =>
        HttpResponse.json({ qr_base_url: null, effective_qr_base_url: "https://homebox.example.com" }),
      ),
    );
    renderWithProviders(<Homebox />, { route: "/homebox" });

    await user.selectOptions(await screen.findByLabelText("Label type for Impact Driver"), "cable_wrap");
    await user.click(screen.getByLabelText("Select Impact Driver"));
    await user.click(await screen.findByRole("button", { name: "Add 1 to tray" }));

    await waitFor(() => expect(useTrayStore.getState().items).toHaveLength(1));
    expect(useTrayStore.getState().items[0]!.definition).toMatchObject({
      type: "cable_wrap",
      params: { lines: ["Impact Driver", "000-001"], qr_data: "https://homebox.example.com/a/000-001" },
    });
  });
});
