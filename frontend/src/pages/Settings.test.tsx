import { describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Settings } from "./Settings";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";

function section(heading: string): HTMLElement {
  const el = screen.getByRole("heading", { name: heading }).closest("section");
  if (!el) throw new Error(`no <section> ancestor for heading "${heading}"`);
  return el as HTMLElement;
}

describe("Settings page", () => {
  it("shows the effective qr_base_url from GET /api/homebox/settings", async () => {
    server.use(
      http.get("/api/homebox/settings", () =>
        HttpResponse.json({ qr_base_url: null, effective_qr_base_url: "https://homebox.example.com" }),
      ),
    );

    renderWithProviders(<Settings />, { route: "/settings" });

    const qrSection = section("QR base URL");
    expect(await within(qrSection).findByText("https://homebox.example.com")).toBeInTheDocument();
    // No stored override -- the input itself starts blank (the fallback is
    // shown as informational text, never pre-filled into the editable field).
    expect(within(qrSection).getByLabelText("QR base URL")).toHaveValue("");
  });

  it("saves the entered value via PUT /api/homebox/settings", async () => {
    const user = userEvent.setup();
    let capturedBody: unknown;
    server.use(
      http.put("/api/homebox/settings", async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json({
          qr_base_url: "https://public.example.com",
          effective_qr_base_url: "https://public.example.com",
        });
      }),
    );

    renderWithProviders(<Settings />, { route: "/settings" });

    const input = await screen.findByLabelText("QR base URL");
    await user.type(input, "https://public.example.com");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(capturedBody).toEqual({ qr_base_url: "https://public.example.com" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Saved.");
  });

  it("shows a 422 validation error readably", async () => {
    const user = userEvent.setup();
    server.use(
      http.put("/api/homebox/settings", () =>
        HttpResponse.json(
          {
            detail: [
              {
                loc: ["body", "qr_base_url"],
                msg: "Value error, qr_base_url must be an http(s) URL, e.g. https://homebox.example.com",
                type: "value_error",
              },
            ],
          },
          { status: 422 },
        ),
      ),
    );

    renderWithProviders(<Settings />, { route: "/settings" });

    const input = await screen.findByLabelText("QR base URL");
    await user.type(input, "not-a-url");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "qr_base_url: qr_base_url must be an http(s) URL, e.g. https://homebox.example.com",
    );
  });

  it("renders the read-only runtime configuration rows from GET /api/settings/runtime", async () => {
    server.use(
      http.get("/api/settings/runtime", () =>
        HttpResponse.json({
          printer_mode: "usb",
          printer_init_strategy: "classic",
          printer_bit_order: "msb_first",
          printer_flip_pins: true,
          els_enabled: true,
          els_tape_mm: 24,
          auth_mode: "oidc",
          homebox_configured: true,
        }),
      ),
    );

    renderWithProviders(<Settings />, { route: "/settings" });

    const runtime = section("Runtime configuration");
    expect(await within(runtime).findByText("usb")).toBeInTheDocument();
    expect(within(runtime).getByText("oidc")).toBeInTheDocument();
    expect(within(runtime).getAllByText("yes").length).toBeGreaterThanOrEqual(3); // flip pins, els enabled, homebox configured
    expect(within(runtime).getByText("24 mm")).toBeInTheDocument();
  });
});
