import { describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Settings } from "./Settings";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";
import { defaultSettingsBody } from "../test/msw/handlers";

function section(heading: string): HTMLElement {
  const el = screen.getByRole("heading", { name: heading }).closest("section");
  if (!el) throw new Error(`no <section> ancestor for heading "${heading}"`);
  return el as HTMLElement;
}

/** Every section past Appearance is gated behind ONE GET /api/settings
 * query at the top of the page (see pages/Settings.tsx) -- none of their
 * headings exist in the DOM until that resolves, so locating one needs an
 * async find, not the synchronous `section()` above (which Appearance
 * itself, rendered unconditionally, doesn't need). */
async function findSection(heading: string): Promise<HTMLElement> {
  const heading_el = await screen.findByRole("heading", { name: heading });
  const el = heading_el.closest("section");
  if (!el) throw new Error(`no <section> ancestor for heading "${heading}"`);
  return el as HTMLElement;
}

/** Scopes to a field's own wrapping element (its labeled control's nearest
 * ancestor <div>) -- several fields on this page have their own visually
 * identical "Save"/"Clear" buttons, so a bare `screen.getByRole("button",
 * {name: "Save"})` would be ambiguous; this narrows to just the one field
 * under test. */
function fieldContainer(labelText: string): HTMLElement {
  const control = screen.getByLabelText(labelText);
  const el = control.closest("div");
  if (!el) throw new Error(`no wrapping <div> for "${labelText}"`);
  return el as HTMLElement;
}

/** A GET /api/settings override with one row patched -- the rest of
 * defaultSettingsBody's rows pass through unchanged. */
function settingsWith(overrides: Record<string, Partial<(typeof defaultSettingsBody)["settings"][number]>>) {
  return {
    settings: defaultSettingsBody.settings.map((row) => (row.key in overrides ? { ...row, ...overrides[row.key] } : row)),
  };
}

describe("Settings page", () => {
  // -- Appearance (unchanged since before this task) -----------------------

  it("shows an Appearance section with the theme toggle, Dark selected by default", async () => {
    renderWithProviders(<Settings />, { route: "/settings" });

    const appearance = section("Appearance");
    const group = within(appearance).getByRole("radiogroup", { name: "Theme" });
    expect(within(group).getByRole("radio", { name: "Dark" })).toHaveAttribute("aria-checked", "true");
    expect(within(group).getByRole("radio", { name: "Light" })).toBeInTheDocument();
    expect(within(group).getByRole("radio", { name: "System" })).toBeInTheDocument();
  });

  it("switching to Light in the Appearance section updates <html data-theme> immediately", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Settings />, { route: "/settings" });

    const appearance = section("Appearance");
    await user.click(within(appearance).getByRole("radio", { name: "Light" }));

    expect(document.documentElement.dataset.theme).toBe("light");
  });

  // -- Printer section ------------------------------------------------------

  describe("Printer section", () => {
    it("shows current values and provenance badges from GET /api/settings", async () => {
      server.use(
        http.get("/api/settings", () =>
          HttpResponse.json(settingsWith({ printer_bit_order: { value: "lsb_first", source: "db" } })),
        ),
      );
      renderWithProviders(<Settings />, { route: "/settings" });

      const printer = await findSection("Printer");
      expect(await within(printer).findByLabelText("Printer mode")).toHaveValue("mock");
      expect(within(printer).getByLabelText("Init strategy")).toHaveValue("classic");
      expect(within(printer).getByLabelText("Bit order")).toHaveValue("lsb_first");
      expect(within(printer).getByRole("switch", { name: "Flip pins" })).toHaveAttribute("aria-checked", "true");
      // "db" provenance shows a Reset to env affordance; the other rows,
      // still at their default provenance, do not.
      expect(within(printer).getByRole("button", { name: "Reset to env" })).toBeInTheDocument();
    });

    it("changing a Select immediately PUTs the new value", async () => {
      const user = userEvent.setup();
      let capturedBody: unknown;
      server.use(
        http.put("/api/settings", async ({ request }) => {
          capturedBody = await request.json();
          return HttpResponse.json(defaultSettingsBody);
        }),
      );
      renderWithProviders(<Settings />, { route: "/settings" });

      const printer = await findSection("Printer");
      const select = await within(printer).findByLabelText("Bit order");
      await user.selectOptions(select, "lsb_first");

      await waitFor(() => expect(capturedBody).toEqual({ printer_bit_order: "lsb_first" }));
    });

    it("toggling the Flip pins switch immediately PUTs the new value", async () => {
      const user = userEvent.setup();
      let capturedBody: unknown;
      server.use(
        http.put("/api/settings", async ({ request }) => {
          capturedBody = await request.json();
          return HttpResponse.json(defaultSettingsBody);
        }),
      );
      renderWithProviders(<Settings />, { route: "/settings" });

      const printer = await findSection("Printer");
      await user.click(await within(printer).findByRole("switch", { name: "Flip pins" }));

      await waitFor(() => expect(capturedBody).toEqual({ printer_flip_pins: false }));
    });

    it("the HomeBox writes switch shows its helper text and PUTs homebox_writes_enabled", async () => {
      const user = userEvent.setup();
      let capturedBody: unknown;
      server.use(
        http.put("/api/settings", async ({ request }) => {
          capturedBody = await request.json();
          return HttpResponse.json(defaultSettingsBody);
        }),
      );
      renderWithProviders(<Settings />, { route: "/settings" });

      const homebox = await findSection("HomeBox");
      const toggle = await within(homebox).findByRole("switch", { name: "Allow writes to HomeBox" });
      expect(toggle).toHaveAttribute("aria-checked", "false");
      expect(
        within(homebox).getByText(
          "Lets this app create items and upload photos in HomeBox. Your HomeBox API key needs write access.",
        ),
      ).toBeInTheDocument();
      await user.click(toggle);

      await waitFor(() => expect(capturedBody).toEqual({ homebox_writes_enabled: true }));
    });

    it("clicking Reset to env PUTs null for that field", async () => {
      const user = userEvent.setup();
      server.use(
        http.get("/api/settings", () =>
          HttpResponse.json(settingsWith({ printer_bit_order: { value: "lsb_first", source: "db" } })),
        ),
      );
      let capturedBody: unknown;
      server.use(
        http.put("/api/settings", async ({ request }) => {
          capturedBody = await request.json();
          return HttpResponse.json(defaultSettingsBody);
        }),
      );
      renderWithProviders(<Settings />, { route: "/settings" });

      const printer = await findSection("Printer");
      await within(printer).findByLabelText("Bit order");
      await user.click(within(printer).getByRole("button", { name: "Reset to env" }));

      await waitFor(() => expect(capturedBody).toEqual({ printer_bit_order: null }));
    });
  });

  // -- Keep-awake poller (commit 6) ------------------------------------------

  describe("Keep-awake fields", () => {
    it("shows the current switch state, interval, and provenance", async () => {
      server.use(
        http.get("/api/settings", () =>
          HttpResponse.json(
            settingsWith({
              keep_printer_awake: { value: true, source: "db" },
              keep_awake_interval_min: { value: 10, source: "db" },
            }),
          ),
        ),
      );
      renderWithProviders(<Settings />, { route: "/settings" });

      const printer = await findSection("Printer");
      expect(await within(printer).findByRole("switch", { name: "Keep printer awake" })).toHaveAttribute(
        "aria-checked",
        "true",
      );
      expect(within(printer).getByLabelText("Keep-awake interval (minutes)")).toHaveValue(10);
      expect(within(printer).getByText(/Sends a status request every N minutes/)).toBeInTheDocument();
    });

    it("toggling Keep printer awake immediately PUTs the new value", async () => {
      const user = userEvent.setup();
      let capturedBody: unknown;
      server.use(
        http.put("/api/settings", async ({ request }) => {
          capturedBody = await request.json();
          return HttpResponse.json(defaultSettingsBody);
        }),
      );
      renderWithProviders(<Settings />, { route: "/settings" });

      const printer = await findSection("Printer");
      await user.click(await within(printer).findByRole("switch", { name: "Keep printer awake" }));

      await waitFor(() => expect(capturedBody).toEqual({ keep_printer_awake: true }));
    });

    it("resetting the keep-awake switch to default (no env tier) PUTs null", async () => {
      const user = userEvent.setup();
      server.use(
        http.get("/api/settings", () =>
          HttpResponse.json(settingsWith({ keep_printer_awake: { value: true, source: "db" } })),
        ),
      );
      let capturedBody: unknown;
      server.use(
        http.put("/api/settings", async ({ request }) => {
          capturedBody = await request.json();
          return HttpResponse.json(defaultSettingsBody);
        }),
      );
      renderWithProviders(<Settings />, { route: "/settings" });

      const printer = await findSection("Printer");
      await within(printer).findByRole("switch", { name: "Keep printer awake" });
      await user.click(within(printer).getByRole("button", { name: "Reset to default" }));

      await waitFor(() => expect(capturedBody).toEqual({ keep_printer_awake: null }));
    });

    it("disables Save and shows an inline error for an out-of-range interval", async () => {
      const user = userEvent.setup();
      renderWithProviders(<Settings />, { route: "/settings" });

      const printer = await findSection("Printer");
      const input = await within(printer).findByLabelText("Keep-awake interval (minutes)");
      await user.clear(input);
      await user.type(input, "100");

      expect(within(printer).getByRole("alert")).toHaveTextContent("must be between 1 and 60");
      expect(within(printer).getByRole("button", { name: "Save" })).toBeDisabled();
    });

    it("saves a valid keep-awake interval", async () => {
      const user = userEvent.setup();
      let capturedBody: unknown;
      server.use(
        http.put("/api/settings", async ({ request }) => {
          capturedBody = await request.json();
          return HttpResponse.json(defaultSettingsBody);
        }),
      );
      renderWithProviders(<Settings />, { route: "/settings" });

      const printer = await findSection("Printer");
      const input = await within(printer).findByLabelText("Keep-awake interval (minutes)");
      await user.clear(input);
      await user.type(input, "15");
      await user.click(within(printer).getByRole("button", { name: "Save" }));

      await waitFor(() => expect(capturedBody).toEqual({ keep_awake_interval_min: 15 }));
    });
  });

  // -- HomeBox section -------------------------------------------------------

  describe("HomeBox section", () => {
    it("saves an edited HomeBox URL", async () => {
      const user = userEvent.setup();
      let capturedBody: unknown;
      server.use(
        http.put("/api/settings", async ({ request }) => {
          capturedBody = await request.json();
          return HttpResponse.json(defaultSettingsBody);
        }),
      );
      renderWithProviders(<Settings />, { route: "/settings" });

      const input = await screen.findByLabelText("HomeBox URL");
      await user.type(input, "https://hb.example.com");
      await user.click(within(fieldContainer("HomeBox URL")).getByRole("button", { name: "Save" }));

      await waitFor(() => expect(capturedBody).toEqual({ homebox_url: "https://hb.example.com" }));
    });

    it("disables Save for a bad URL scheme and shows an inline error", async () => {
      const user = userEvent.setup();
      renderWithProviders(<Settings />, { route: "/settings" });

      const input = await screen.findByLabelText("HomeBox URL");
      await user.clear(input);
      await user.type(input, "ftp://x");

      const container = fieldContainer("HomeBox URL");
      expect(within(container).getByRole("alert")).toHaveTextContent("http(s)");
      expect(within(container).getByRole("button", { name: "Save" })).toBeDisabled();
    });

    it("Clear on the HomeBox URL field PUTs null", async () => {
      const user = userEvent.setup();
      let capturedBody: unknown;
      server.use(
        http.put("/api/settings", async ({ request }) => {
          capturedBody = await request.json();
          return HttpResponse.json(defaultSettingsBody);
        }),
      );
      renderWithProviders(<Settings />, { route: "/settings" });

      await screen.findByLabelText("HomeBox URL");
      await user.click(within(fieldContainer("HomeBox URL")).getByRole("button", { name: "Clear (use env)" }));

      await waitFor(() => expect(capturedBody).toEqual({ homebox_url: null }));
    });

    it("shows Not set and no Clear button when the API key is unset, and never pre-fills the input", async () => {
      renderWithProviders(<Settings />, { route: "/settings" });

      const input = await screen.findByLabelText("HomeBox API key");
      expect(input).toHaveValue("");
      const container = fieldContainer("HomeBox API key");
      expect(within(container).queryByRole("button", { name: "Clear" })).not.toBeInTheDocument();
      expect(screen.getByText("Not set.")).toBeInTheDocument();
    });

    it("shows Key set and a Clear button when the API key is set, still starting blank", async () => {
      server.use(
        http.get("/api/settings", () => HttpResponse.json(settingsWith({ homebox_api_key: { set: true, source: "db" } }))),
      );
      renderWithProviders(<Settings />, { route: "/settings" });

      const input = await screen.findByLabelText("HomeBox API key");
      expect(input).toHaveValue("");
      expect(await screen.findByText("Key set.")).toBeInTheDocument();
      expect(within(fieldContainer("HomeBox API key")).getByRole("button", { name: "Clear" })).toBeInTheDocument();
    });

    it("saving a new API key sends it and clears the input afterward, never echoing it anywhere", async () => {
      const user = userEvent.setup();
      let capturedBody: unknown;
      server.use(
        http.put("/api/settings", async ({ request }) => {
          capturedBody = await request.json();
          return HttpResponse.json(settingsWith({ homebox_api_key: { set: true, source: "db" } }));
        }),
      );
      renderWithProviders(<Settings />, { route: "/settings" });

      const input = await screen.findByLabelText("HomeBox API key");
      await user.type(input, "hb_super_secret_plant");
      await user.click(within(fieldContainer("HomeBox API key")).getByRole("button", { name: "Save" }));

      await waitFor(() => expect(capturedBody).toEqual({ homebox_api_key: "hb_super_secret_plant" }));
      await waitFor(() => expect(screen.getByLabelText("HomeBox API key")).toHaveValue(""));
      expect(document.body.textContent).not.toContain("hb_super_secret_plant");
    });

    // -- QR base URL (unchanged behavior from before this task) -------------

    it("shows the effective qr_base_url from GET /api/homebox/settings", async () => {
      server.use(
        http.get("/api/homebox/settings", () =>
          HttpResponse.json({ qr_base_url: null, effective_qr_base_url: "https://homebox.example.com" }),
        ),
      );

      renderWithProviders(<Settings />, { route: "/settings" });

      const qrSection = await findSection("QR base URL");
      expect(await within(qrSection).findByText("https://homebox.example.com")).toBeInTheDocument();
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

      const qrSection = await findSection("QR base URL");
      const input = await within(qrSection).findByLabelText("QR base URL");
      await user.type(input, "https://public.example.com");
      await user.click(within(qrSection).getByRole("button", { name: "Save" }));

      await waitFor(() => expect(capturedBody).toEqual({ qr_base_url: "https://public.example.com" }));
      expect(await within(qrSection).findByRole("status")).toHaveTextContent("Saved.");
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

      const qrSection = await findSection("QR base URL");
      const input = await within(qrSection).findByLabelText("QR base URL");
      await user.type(input, "not-a-url");
      await user.click(within(qrSection).getByRole("button", { name: "Save" }));

      expect(await within(qrSection).findByRole("alert")).toHaveTextContent(
        "qr_base_url: qr_base_url must be an http(s) URL, e.g. https://homebox.example.com",
      );
    });
  });

  // -- ELS section -----------------------------------------------------------

  describe("ELS section", () => {
    it("shows the current tape width and whether ELS is enabled", async () => {
      server.use(
        http.get("/api/settings", () =>
          HttpResponse.json(settingsWith({ els_enabled: { value: true, source: "db", editable: true } })),
        ),
      );
      renderWithProviders(<Settings />, { route: "/settings" });

      const els = await findSection("ELS");
      expect(await within(els).findByRole("switch", { name: "ELS enabled" })).toHaveAttribute("aria-checked", "true");
      expect(within(els).getByLabelText("ELS tape width (mm)")).toHaveValue(24);
      expect(within(els).getByText("enabled")).toBeInTheDocument();
    });

    it("toggling ELS enabled immediately PUTs the new value", async () => {
      const user = userEvent.setup();
      let capturedBody: unknown;
      server.use(
        http.put("/api/settings", async ({ request }) => {
          capturedBody = await request.json();
          return HttpResponse.json(defaultSettingsBody);
        }),
      );
      renderWithProviders(<Settings />, { route: "/settings" });

      const els = await findSection("ELS");
      await user.click(await within(els).findByRole("switch", { name: "ELS enabled" }));

      await waitFor(() => expect(capturedBody).toEqual({ els_enabled: true }));
    });

    it("clicking Reset to env on ELS enabled PUTs null for that field", async () => {
      const user = userEvent.setup();
      server.use(
        http.get("/api/settings", () =>
          HttpResponse.json(settingsWith({ els_enabled: { value: true, source: "db", editable: true } })),
        ),
      );
      let capturedBody: unknown;
      server.use(
        http.put("/api/settings", async ({ request }) => {
          capturedBody = await request.json();
          return HttpResponse.json(defaultSettingsBody);
        }),
      );
      renderWithProviders(<Settings />, { route: "/settings" });

      const els = await findSection("ELS");
      await within(els).findByRole("switch", { name: "ELS enabled" });
      await user.click(within(els).getByRole("button", { name: "Reset to env" }));

      await waitFor(() => expect(capturedBody).toEqual({ els_enabled: null }));
    });

    it("disables Save and shows an inline error for an out-of-range tape width", async () => {
      const user = userEvent.setup();
      renderWithProviders(<Settings />, { route: "/settings" });

      const els = await findSection("ELS");
      const input = await within(els).findByLabelText("ELS tape width (mm)");
      await user.clear(input);
      await user.type(input, "100");

      expect(within(els).getByRole("alert")).toHaveTextContent("must be between 3.5 and 36");
      expect(within(els).getByRole("button", { name: "Save" })).toBeDisabled();
    });

    it("saves a valid tape width", async () => {
      const user = userEvent.setup();
      let capturedBody: unknown;
      server.use(
        http.put("/api/settings", async ({ request }) => {
          capturedBody = await request.json();
          return HttpResponse.json(defaultSettingsBody);
        }),
      );
      renderWithProviders(<Settings />, { route: "/settings" });

      const els = await findSection("ELS");
      const input = await within(els).findByLabelText("ELS tape width (mm)");
      await user.clear(input);
      await user.type(input, "12");
      await user.click(within(els).getByRole("button", { name: "Save" }));

      await waitFor(() => expect(capturedBody).toEqual({ els_tape_mm: 12 }));
    });
  });

  // -- Runtime section (read-only) --------------------------------------------

  it("renders the read-only Runtime rows from GET /api/settings", async () => {
    server.use(
      http.get("/api/settings", () => HttpResponse.json(settingsWith({ auth_mode: { value: "oidc" } }))),
    );

    renderWithProviders(<Settings />, { route: "/settings" });

    const runtime = await findSection("Runtime");
    expect(await within(runtime).findByText("oidc")).toBeInTheDocument();
    expect(within(runtime).getByText("http://localhost:5173")).toBeInTheDocument(); // cors_origins
    expect(within(runtime).getByText("./data")).toBeInTheDocument(); // data_dir
  });

  it("ELS enabled no longer appears in the read-only Runtime section (task 4.5 Track A: it moved to ELS)", async () => {
    renderWithProviders(<Settings />, { route: "/settings" });

    const runtime = await findSection("Runtime");
    expect(within(runtime).queryByText("ELS enabled")).not.toBeInTheDocument();
  });
});
