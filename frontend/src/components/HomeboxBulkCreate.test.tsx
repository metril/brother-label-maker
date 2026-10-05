import { afterEach, describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { HomeboxBulkCreate } from "./HomeboxBulkCreate";
import { useDesignerStore } from "../stores/designer";
import { useTrayStore } from "../stores/tray";
import { useTrayDrawerStore } from "../stores/trayDrawer";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";

const INITIAL_DESIGNER_STATE = useDesignerStore.getState();
const INITIAL_TRAY_STATE = useTrayStore.getState();
const INITIAL_DRAWER_STATE = useTrayDrawerStore.getState();

afterEach(() => {
  useDesignerStore.setState(INITIAL_DESIGNER_STATE, true);
  useTrayStore.setState(INITIAL_TRAY_STATE, true);
  useTrayDrawerStore.setState(INITIAL_DRAWER_STATE, true);
});

const PARENT = { id: "loc-1", name: "Garage" };

function useTagsHandler() {
  server.use(http.get("/api/homebox/tags", () => HttpResponse.json([{ id: "t1", name: "cables" }])));
}

describe("HomeboxBulkCreate", () => {
  it("creates the expanded names, reports a failed row, and queues labels for the ok rows", async () => {
    const user = userEvent.setup();
    useTagsHandler();
    let captured: unknown;
    server.use(
      http.post("/api/homebox/entities/bulk", async ({ request }) => {
        captured = await request.json();
        return HttpResponse.json({
          results: [
            { index: 0, ok: true, entity: { id: "e1", name: "Cable 1", asset_id: "000-001" }, error: null },
            { index: 1, ok: false, entity: null, error: "HomeBox rejected the request (HTTP 422): boom" },
            { index: 2, ok: true, entity: { id: "e3", name: "Cable 3", asset_id: "000-003" }, error: null },
          ],
        });
      }),
      http.get("/api/homebox/settings", () =>
        HttpResponse.json({ qr_base_url: null, effective_qr_base_url: "https://hb.example.com" }),
      ),
    );
    renderWithProviders(<HomeboxBulkCreate parent={PARENT} />);

    const count = screen.getByLabelText("Count");
    await user.clear(count);
    await user.type(count, "3");
    await user.click(await screen.findByLabelText("cables"));
    const button = await screen.findByRole("button", { name: "Create 3 & print" });
    await waitFor(() => expect(button).toBeEnabled());
    await user.click(button);

    await waitFor(() => expect(captured).toEqual({ parent_id: "loc-1", tag_ids: ["t1"], names: ["Cable 1", "Cable 2", "Cable 3"] }));
    expect(await screen.findByText(/422\): boom/)).toBeInTheDocument();
    expect(screen.getByText(/Created 2 of 3/)).toBeInTheDocument();

    await waitFor(() => expect(useTrayStore.getState().items).toHaveLength(2));
    const defs = useTrayStore.getState().items.map((i) => i.definition);
    expect(defs.map((d) => d.type)).toEqual(["cable_wrap", "cable_wrap"]);
    expect(defs[0]!.params).toMatchObject({ lines: ["Cable 1", "000-001"], qr_data: "https://hb.example.com/a/000-001" });
    expect(useTrayDrawerStore.getState().open).toBe(true);
  });

  it("sends entity type, quantity and description only when set", async () => {
    const user = userEvent.setup();
    useTagsHandler();
    const bodies: unknown[] = [];
    server.use(
      http.get("/api/homebox/entity-types", () => HttpResponse.json([{ id: "et1", name: "Cable" }])),
      http.post("/api/homebox/entities/bulk", async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json({ results: [] });
      }),
    );
    renderWithProviders(<HomeboxBulkCreate parent={PARENT} />);

    const count = screen.getByLabelText("Count");
    await user.clear(count);
    await user.type(count, "1");
    const button = await screen.findByRole("button", { name: "Create 1 & print" });
    await waitFor(() => expect(button).toBeEnabled());
    await user.click(button);
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toEqual({ parent_id: "loc-1", tag_ids: [], names: ["Cable 1"] });

    await screen.findByRole("option", { name: "Cable" });
    await user.selectOptions(screen.getByLabelText("Entity type"), "et1");
    await user.type(screen.getByLabelText("Quantity"), "4");
    await user.type(screen.getByLabelText("Description"), "Spare {{seq}");
    await user.click(button);
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toEqual({
      parent_id: "loc-1",
      tag_ids: [],
      names: ["Cable 1"],
      entity_type_id: "et1",
      quantity: 4,
      description: "Spare {seq}",
    });
  });

  it("homebox_asset label type with Show QR off builds show_qr false", async () => {
    const user = userEvent.setup();
    useTagsHandler();
    server.use(
      http.post("/api/homebox/entities/bulk", () =>
        HttpResponse.json({
          results: [{ index: 0, ok: true, entity: { id: "e1", name: "Cable 1", asset_id: "000-001" }, error: null }],
        }),
      ),
      http.get("/api/homebox/settings", () =>
        HttpResponse.json({ qr_base_url: null, effective_qr_base_url: "https://hb.example.com" }),
      ),
      http.get("/api/homebox/entities/:id/path", () => HttpResponse.json([{ id: "loc-1", name: "Garage", type: "location" }])),
    );
    renderWithProviders(<HomeboxBulkCreate parent={PARENT} />);

    const count = screen.getByLabelText("Count");
    await user.clear(count);
    await user.type(count, "1");
    await user.selectOptions(screen.getByLabelText("Label type"), "homebox_asset");
    await user.click(screen.getByRole("switch", { name: "Show QR" }));
    const button = await screen.findByRole("button", { name: "Create 1 & print" });
    await waitFor(() => expect(button).toBeEnabled());
    await user.click(button);

    await waitFor(() => expect(useTrayStore.getState().items).toHaveLength(1));
    const def = useTrayStore.getState().items[0]!.definition;
    expect(def.type).toBe("homebox_asset");
    expect(def.params).toMatchObject({ asset_id: "000-001", location: "Garage", show_qr: false });
  });

  it("is disabled without a parent location and when the pattern lacks {seq}", async () => {
    const user = userEvent.setup();
    useTagsHandler();
    const { unmount } = renderWithProviders(<HomeboxBulkCreate parent={null} />);
    expect(await screen.findByText("Select a parent location in the tree first.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Create/ })).toBeDisabled();
    unmount();

    renderWithProviders(<HomeboxBulkCreate parent={PARENT} />);
    const pattern = screen.getByLabelText("Name pattern");
    await user.clear(pattern);
    await user.type(pattern, "Plain");
    expect(await screen.findByText(/Add \{seq\} to the pattern/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Create/ })).toBeDisabled();
  });

  it("shows the server error when the whole bulk request is rejected", async () => {
    const user = userEvent.setup();
    useTagsHandler();
    server.use(http.post("/api/homebox/entities/bulk", () => HttpResponse.json({ detail: "homebox writes disabled" }, { status: 403 })));
    renderWithProviders(<HomeboxBulkCreate parent={PARENT} />);

    const button = await screen.findByRole("button", { name: "Create 5 & print" });
    await waitFor(() => expect(button).toBeEnabled());
    await user.click(button);

    expect(await screen.findByRole("alert")).toHaveTextContent("homebox writes disabled");
    expect(useTrayStore.getState().items).toHaveLength(0);
  });
});
