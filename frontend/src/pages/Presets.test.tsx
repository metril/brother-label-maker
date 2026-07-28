import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Presets } from "./Presets";
import { useDesignerStore } from "../stores/designer";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";

const INITIAL_DESIGNER_STATE = useDesignerStore.getState();

afterEach(() => {
  useDesignerStore.setState(INITIAL_DESIGNER_STATE, true);
});

function preset(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "preset-1",
    name: "Rack uplink",
    label_type: "text",
    definition: { lines: ["UPLINK"] },
    tape_width_mm: 24,
    tape_family: "tze",
    favorite: false,
    created_at: "2026-07-27T11:00:00.000000Z",
    updated_at: "2026-07-27T11:55:00.000000Z",
    ...overrides,
  };
}

describe("Presets page", () => {
  it("renders the empty state when there are no presets", async () => {
    server.use(http.get("/api/presets", () => HttpResponse.json([])));
    renderWithProviders(<Presets />);

    expect(await screen.findByText("No presets yet. Design a label and choose Save as preset to reuse it.")).toBeInTheDocument();
  });

  it("renders a card per preset from the mocked API, with type/tape/favorite", async () => {
    server.use(http.get("/api/presets", () => HttpResponse.json([preset(), preset({ id: "preset-2", name: "Any tape design", tape_width_mm: null, favorite: true })])));
    renderWithProviders(<Presets />);

    expect(await screen.findByText("Rack uplink")).toBeInTheDocument();
    expect(screen.getByText("24mm TZe")).toBeInTheDocument();
    expect(screen.getByText("Any tape design")).toBeInTheDocument();
    expect(screen.getByText("Any tape")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unmark Any tape design as favorite" })).toHaveAttribute("aria-pressed", "true");
  });

  it("search and type filter drive GET /api/presets' own query params", async () => {
    const user = userEvent.setup();
    const seenQueries: URLSearchParams[] = [];
    server.use(
      http.get("/api/presets", ({ request }) => {
        seenQueries.push(new URL(request.url).searchParams);
        return HttpResponse.json([preset()]);
      }),
    );
    renderWithProviders(<Presets />);
    await screen.findByText("Rack uplink");

    await user.type(screen.getByLabelText("Search"), "uplink");
    await waitFor(() => expect(seenQueries.at(-1)?.get("q")).toBe("uplink"));

    await user.selectOptions(screen.getByLabelText("Type"), "text");
    await waitFor(() => expect(seenQueries.at(-1)?.get("label_type")).toBe("text"));
  });

  it("Load into designer sets the type/params/tape and navigates to /", async () => {
    const user = userEvent.setup();
    server.use(http.get("/api/presets", () => HttpResponse.json([preset({ definition: { lines: ["FROM PRESET"] } })])));
    renderWithProviders(<Presets />, { route: "/presets" });

    await user.click(await screen.findByRole("button", { name: "Load" }));

    await waitFor(() => {
      expect(useDesignerStore.getState().selectedType).toBe("text");
      expect(useDesignerStore.getState().paramsByType.text?.lines).toEqual(["FROM PRESET"]);
      expect(useDesignerStore.getState().tape).toEqual({ width_mm: 24, family: "tze" });
    });
  });

  it("favorite toggle PUTs the flipped value", async () => {
    const user = userEvent.setup();
    let capturedBody: unknown;
    server.use(
      http.get("/api/presets", () => HttpResponse.json([preset({ favorite: false })])),
      http.put("/api/presets/preset-1", async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json(preset({ favorite: true }));
      }),
    );
    renderWithProviders(<Presets />);

    await user.click(await screen.findByRole("button", { name: "Mark Rack uplink as favorite" }));
    await waitFor(() => expect(capturedBody).toEqual({ favorite: true }));
  });

  it("Delete asks for confirmation (a keyboard-operable dialog) before DELETEing", async () => {
    const user = userEvent.setup();
    const deleteSpy = vi.fn();
    server.use(
      http.get("/api/presets", () => HttpResponse.json([preset()])),
      http.delete("/api/presets/preset-1", () => {
        deleteSpy();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderWithProviders(<Presets />);

    await user.click(await screen.findByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("dialog", { name: "Delete Rack uplink?" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(deleteSpy).not.toHaveBeenCalled();

    // Cancel first: no DELETE fires, and Escape/Cancel both close it.
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(deleteSpy).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Delete" }));
    await within(await screen.findByRole("dialog")).findByRole("button", { name: "Cancel" });
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(deleteSpy).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
