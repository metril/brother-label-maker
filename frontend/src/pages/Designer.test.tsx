import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Designer } from "./Designer";
import { GlobalTrayDrawer } from "../components/GlobalTrayDrawer";
import { useDesignerStore } from "../stores/designer";
import { useTrayStore } from "../stores/tray";
import { buildDefaultParams } from "../schema/defaults";
import type { JsonSchemaObject } from "../schema/jsonSchema";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";
import { TINY_PNG_B64 } from "../test/msw/handlers";
import labelTypesFixture from "../test/fixtures/label-types.json";

interface FixtureType {
  type: string;
  title: string;
  params_schema: JsonSchemaObject;
}

const LABEL_TYPES = labelTypesFixture as unknown as FixtureType[];
const PATCH_PANEL_TYPE = LABEL_TYPES.find((t) => t.type === "patch_panel")!;

// useDesignerStore is a module-level singleton (zustand) -- reset it after
// each test so a click on a different tape width (or typed content) in one
// test can't leak into the next.
const INITIAL_STORE_STATE = useDesignerStore.getState();
const INITIAL_TRAY_STATE = useTrayStore.getState();

afterEach(() => {
  useDesignerStore.setState(INITIAL_STORE_STATE, true);
  useTrayStore.setState(INITIAL_TRAY_STATE, true);
});

function connectedStatusBody(mediaWidthMm: number) {
  return {
    connected: true,
    printer_mode: "mock",
    status: {
      model_code: 129,
      series_code: 48,
      country_code: 48,
      error_info1: 0,
      error_info2: 0,
      media_width_mm: mediaWidthMm,
      media_type_raw: 20,
      media_type: 1,
      number_of_colors: 1,
      status_type_raw: 0,
      status_type: 0,
      phase_type: 0,
      phase_number: 0,
      tape_color_raw: 144,
      text_color_raw: 8,
      raw_hex: "80 20 42 30 81 30",
      errors: [],
      has_error: false,
      is_e720bt: true,
    },
    error: null,
  };
}

// I1: banner appears on mismatch, absent on match/disconnected. Designer's
// default tape (stores/designer.ts's initial state) is 24mm.
describe("Designer tape-mismatch banner (I1)", () => {
  it("shows exactly one amber banner (role=alert) when the loaded tape doesn't match the design", async () => {
    server.use(
      http.get("/api/printer/status", () => HttpResponse.json(connectedStatusBody(12))),
    );

    renderWithProviders(<Designer />);

    const message = "Printer has 12mm tape loaded — this label is designed for 24mm";
    const matches = await screen.findAllByText(message);
    // Shown once (the hero banner, role="alert") -- a duplicate copy next
    // to the Print button was removed: role="alert" is already announced
    // immediately, and the Job panel sits directly below the hero on every
    // viewport, so a second copy was pure redundancy, not reinforcement.
    expect(matches).toHaveLength(1);
    expect(screen.getByRole("alert")).toHaveTextContent(message);
  });

  it("shows no banner when the loaded tape matches the design", async () => {
    const statusSpy = vi.fn();
    server.use(
      http.get("/api/printer/status", () => {
        statusSpy();
        return HttpResponse.json(connectedStatusBody(24));
      }),
    );

    renderWithProviders(<Designer />);

    await waitFor(() => expect(statusSpy).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.queryByText(/this label is designed for/)).not.toBeInTheDocument(),
    );
  });

  it("shows no banner while the printer is disconnected", async () => {
    const statusSpy = vi.fn();
    server.use(
      http.get("/api/printer/status", () => {
        statusSpy();
        return HttpResponse.json({
          connected: false,
          printer_mode: "usb",
          status: null,
          error: "printer not found",
        });
      }),
    );

    renderWithProviders(<Designer />);

    await waitFor(() => expect(statusSpy).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.queryByText(/this label is designed for/)).not.toBeInTheDocument(),
    );
  });
});

// The Designer page no longer renders any tray UI of its own -- it shares
// components/GlobalTrayDrawer.tsx (header button + slide-over) with every
// other route now (see that component's own docstring and
// stores/currentDesign.ts). Pins the one-tray-path: no leftover JobTray
// testids, and no second "Print" affordance hiding somewhere in Designer's
// own tree.
describe("Designer -- no inline tray UI (tray unified into GlobalTrayDrawer)", () => {
  it("renders no job-tray UI of its own", async () => {
    renderWithProviders(<Designer />);

    await screen.findByLabelText("Lines 1");
    expect(screen.queryByTestId("job-tray-panel")).not.toBeInTheDocument();
    expect(screen.queryByTestId("job-tray-mobile-bar")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Print/ })).not.toBeInTheDocument();
  });
});

describe("Designer -- Add to tray (via GlobalTrayDrawer, current-design mirror)", () => {
  it("snapshots the current design as a DEEP COPY -- editing the form afterward never retroactively changes the queued item", async () => {
    const user = userEvent.setup();
    // GlobalTrayDrawer is mounted alongside Designer here the same way
    // AppShell.tsx mounts it (a sibling, not a Designer child) -- Designer
    // only feeds it stores/currentDesign.ts's mirror now, it doesn't render
    // any tray UI of its own (see the describe block above).
    renderWithProviders(
      <>
        <Designer />
        <GlobalTrayDrawer />
      </>,
    );

    const lines1 = await screen.findByLabelText("Lines 1");
    await user.type(lines1, "UPLINK-A");

    await user.click(await screen.findByRole("button", { name: "Tray" }));

    const addButton = await screen.findByRole("button", { name: "+ Add to tray" });
    await waitFor(() => expect(addButton).not.toBeDisabled());
    await user.click(addButton);

    expect(await screen.findByText("Text — UPLINK-A")).toBeInTheDocument();

    await user.clear(lines1);
    await user.type(lines1, "CHANGED");

    expect(screen.getByText("Text — UPLINK-A")).toBeInTheDocument();
    expect(screen.queryByText("Text — CHANGED")).not.toBeInTheDocument();
  });
});

describe("Designer warning-chip -> form-row focus wiring", () => {
  it("clicking a warning chip with an object_id focuses and highlights the matching block row in the form", async () => {
    const user = userEvent.setup();
    useDesignerStore.getState().selectType("patch_panel", PATCH_PANEL_TYPE.params_schema);
    useDesignerStore.getState().setParams("patch_panel", {
      ...buildDefaultParams(PATCH_PANEL_TYPE.params_schema),
      blocks: [{ lines: ["a very long line that would get truncated"] }],
    });

    server.use(
      http.post("/api/render/preview", () =>
        HttpResponse.json({
          png_b64: TINY_PNG_B64,
          png_width_px: 200,
          png_height_px: 96,
          length_mm: 30,
          min_feed_mm: 24.5,
          warnings: [
            { code: "text_truncated", severity: "warning", message: "block 0: text truncated", object_id: "block-0" },
          ],
          total_labels: null,
          sequence_value: null,
        }),
      ),
    );

    renderWithProviders(<Designer />);

    const chip = await screen.findByRole("button", { name: "block 0: text truncated" });
    const row = document.getElementById("block-0")!;
    expect(row.className).not.toContain("border-amber-500");

    await user.click(chip);

    expect(row.className).toContain("border-amber-500");
    expect(document.activeElement).toBe(row);
  });
});

// track C3: the feed deck's own preview-zoom control. The default preview
// mock (test/msw/handlers.ts's previewHandler) returns length_mm: 25.4, so
// the printable band's on-screen width is a direct, exact function of
// whichever zoom level is selected (25.4 * pxPerMm) -- no rounding at any
// of 2x/4x/8x (25.4*2 = 50.8, *4 = 101.6, *8 = 203.2).
describe("Designer -- preview zoom (track C3)", () => {
  it("defaults to 4x and rescales the printable band's on-screen width when a different zoom level is selected", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Designer />);

    const lines1 = await screen.findByLabelText("Lines 1");
    await user.type(lines1, "UPLINK-A");

    const band = await screen.findByTestId("printable-band");
    await waitFor(() => expect(band).toHaveStyle({ width: "101.6px" })); // 25.4mm * 4x (default)

    await user.click(screen.getByRole("radio", { name: "8×" }));
    await waitFor(() => expect(screen.getByTestId("printable-band")).toHaveStyle({ width: "203.2px" })); // 25.4mm * 8x

    await user.click(screen.getByRole("radio", { name: "2×" }));
    await waitFor(() => expect(screen.getByTestId("printable-band")).toHaveStyle({ width: "50.8px" })); // 25.4mm * 2x
  });
});
