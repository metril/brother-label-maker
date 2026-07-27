import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { Designer } from "./Designer";
import { useDesignerStore } from "../stores/designer";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";

// useDesignerStore is a module-level singleton (zustand) -- reset it after
// each test so a click on a different tape width (or typed content) in one
// test can't leak into the next.
const INITIAL_STORE_STATE = useDesignerStore.getState();

afterEach(() => {
  useDesignerStore.setState(INITIAL_STORE_STATE, true);
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
  it("shows an amber banner and a matching warning next to the Print button when the loaded tape doesn't match the design", async () => {
    server.use(
      http.get("/api/printer/status", () => HttpResponse.json(connectedStatusBody(12))),
    );

    renderWithProviders(<Designer />);

    const message = "Printer has 12mm tape loaded — this label is designed for 24mm";
    const matches = await screen.findAllByText(message);
    // Once as the banner (role="alert"), once next to the Print button.
    expect(matches).toHaveLength(2);
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
