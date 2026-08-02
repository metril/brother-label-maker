import { describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { Diagnostics } from "./Diagnostics";
import { renderWithProviders } from "../test/utils";
import { inertKeepAliveStatus } from "../test/msw/handlers";
import { server } from "../test/msw/server";

function section(heading: string): HTMLElement {
  const el = screen.getByRole("heading", { name: heading }).closest("section");
  if (!el) throw new Error(`no <section> ancestor for heading "${heading}"`);
  return el as HTMLElement;
}

describe("Diagnostics page", () => {
  it("renders all four sections from mocked responses, including the raw-byte hex display", async () => {
    server.use(
      http.get("/api/history", () =>
        HttpResponse.json({
          items: [
            {
              id: "job-recent-1",
              created_at: "2026-07-28T00:00:00.000000Z",
              status: "done",
              error: null,
              label_count: 1,
              chain_mode: "cut_each",
              strategy: "classic",
              tape_width_mm: 24,
              tape_used_mm: 30,
              thumbnail_url: null,
            },
          ],
          page: 1,
          page_size: 5,
          total: 1,
        }),
      ),
    );

    renderWithProviders(<Diagnostics />, { route: "/diagnostics" });

    expect(screen.getByRole("heading", { name: "Diagnostics" })).toBeInTheDocument();

    // Printer section: default msw status has media_type_raw=20 (0x14) and
    // a recognized media_type=1 -- the raw hex block AND the decoded byte11
    // interpretation both render.
    const printer = section("Printer");
    expect(await within(printer).findByText("80 20 42 30 81 30")).toBeInTheDocument();
    expect(within(printer).getByText(/laminated \(TZe\) \(0x14\)/)).toBeInTheDocument();
    expect(within(within(printer).getByText("Connected").closest("div")!).getByText("yes")).toBeInTheDocument();

    // HomeBox section: configured/reachable/healthy/version/error, fully
    // rendered from the mocked GET /api/homebox/status.
    const homebox = section("HomeBox");
    expect(await within(homebox).findByText("0.26.2")).toBeInTheDocument();

    // App section: /api/health's printer_mode + version, auth mode from
    // GET /api/auth/me, and the WS connection state (auto-opens under
    // test, see test/setup.ts's MockWebSocket).
    const app = section("App");
    expect(await within(app).findByText("0.1.0")).toBeInTheDocument();
    expect(within(app).getByText("none")).toBeInTheDocument();
    await waitFor(() => expect(within(app).getByText("live")).toBeInTheDocument());

    // Print worker section: the last 5 jobs (here, 1) via GET /api/history,
    // plus a link to the full History page.
    const worker = section("Print worker");
    expect(await within(worker).findByText("job-recent-1")).toBeInTheDocument();
    expect(within(worker).getByText("Done")).toBeInTheDocument();
    expect(within(worker).getByRole("link", { name: "View all history" })).toHaveAttribute("href", "/history");
  });

  it("an unrecognized media byte renders the explicit unknown state", async () => {
    server.use(
      http.get("/api/printer/status", () =>
        HttpResponse.json({
          connected: true,
          printer_mode: "mock",
          status: {
            model_code: 129,
            series_code: 48,
            country_code: 48,
            error_info1: 0,
            error_info2: 0,
            media_width_mm: 24,
            media_type_raw: 20,
            media_type: null,
            number_of_colors: 1,
            status_type_raw: 0,
            status_type: 0,
            phase_type: 0,
            phase_number: 0,
            tape_color_raw: 144,
            text_color_raw: 8,
            raw_hex: "80 20 42 30 81 30 00 00 00 00 18 14 01 00 00 00 00 00 00 00 00 00 00 00 90 08 00 00 00 00 00 00",
            errors: [],
            has_error: false,
            is_e720bt: true,
          },
          error: null,
          keep_alive: inertKeepAliveStatus,
        }),
      ),
    );

    renderWithProviders(<Diagnostics />, { route: "/diagnostics" });

    expect(await screen.findByText(/unknown -- byte 0x14 is not decoded by this app/)).toBeInTheDocument();
  });

  it("shows the keep-awake poller's status in the Printer section", async () => {
    server.use(
      http.get("/api/printer/status", () =>
        HttpResponse.json({
          connected: true,
          printer_mode: "usb",
          status: null,
          error: null,
          keep_alive: {
            enabled: true,
            last_attempt_at: "2026-08-02T04:00:00.000000Z",
            last_result: "ok",
            last_error: null,
          },
        }),
      ),
    );

    renderWithProviders(<Diagnostics />, { route: "/diagnostics" });

    const printer = await screen.findByRole("heading", { name: "Printer" }).then((h) => h.closest("section")!);
    const keepAwakeRow = await within(printer).findByText("Keep-awake").then((el) => el.closest("div")!);
    expect(within(keepAwakeRow).getByText("yes")).toBeInTheDocument();
    expect(within(printer).getByText("OK")).toBeInTheDocument();
  });

  it("shows a readable label and the raw error for a keep-awake poll failure", async () => {
    server.use(
      http.get("/api/printer/status", () =>
        HttpResponse.json({
          connected: false,
          printer_mode: "usb",
          status: null,
          error: "no USB printer found",
          keep_alive: {
            enabled: true,
            last_attempt_at: "2026-08-02T04:00:00.000000Z",
            last_result: "error",
            last_error: "USB error opening printer: no backend available",
          },
        }),
      ),
    );

    renderWithProviders(<Diagnostics />, { route: "/diagnostics" });

    const printer = await screen.findByRole("heading", { name: "Printer" }).then((h) => h.closest("section")!);
    expect(await within(printer).findByText("Error")).toBeInTheDocument();
    expect(within(printer).getByText("USB error opening printer: no backend available")).toBeInTheDocument();
  });
});
