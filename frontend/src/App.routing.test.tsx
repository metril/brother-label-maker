import { afterEach, describe, expect, it } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import App from "./App";
import { server } from "./test/msw/server";
import { useDesignerStore } from "./stores/designer";
import { useTrayStore } from "./stores/tray";

// stores/designer.ts + stores/tray.ts are module-level zustand singletons --
// reset between tests so navigating/typing in one test can't leak state
// into the next (same convention as pages/Designer.test.tsx).
const INITIAL_DESIGNER_STATE = useDesignerStore.getState();
const INITIAL_TRAY_STATE = useTrayStore.getState();

afterEach(() => {
  useDesignerStore.setState(INITIAL_DESIGNER_STATE, true);
  useTrayStore.setState(INITIAL_TRAY_STATE, true);
});

describe("App routing (task 2.13)", () => {
  it("the primary nav links navigate between Design/Presets/History and mark the active route with aria-current", async () => {
    const user = userEvent.setup();
    render(<App />);

    const nav = screen.getByRole("navigation", { name: "Sections" });
    expect(await within(nav).findByRole("link", { name: "Design" })).toHaveAttribute("aria-current", "page");

    // Task 3.4: HomeBox is a real NavLink once GET /api/homebox/status
    // reports `configured` -- the default msw handler does. The
    // unconfigured placeholder branch is covered by this suite's own
    // "disabled placeholder" test below.
    const homeboxLink = await within(nav).findByRole("link", { name: "HomeBox" });
    expect(homeboxLink).not.toHaveAttribute("aria-current");

    await user.click(within(nav).getByRole("link", { name: "Presets" }));
    expect(await screen.findByRole("heading", { name: "Presets" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Presets" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Design" })).not.toHaveAttribute("aria-current");

    await user.click(within(nav).getByRole("link", { name: "History" }));
    expect(await screen.findByRole("heading", { name: "History" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "History" })).toHaveAttribute("aria-current", "page");

    await user.click(within(nav).getByRole("link", { name: "HomeBox" }));
    expect(await screen.findByRole("heading", { name: "HomeBox" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "HomeBox" })).toHaveAttribute("aria-current", "page");

    await user.click(within(nav).getByRole("link", { name: "Design" }));
    expect(await screen.findByRole("heading", { name: "Text" })).toBeInTheDocument();
  });

  it("Library is a working nav link between Gallery and Diagnostics", async () => {
    const user = userEvent.setup();
    render(<App />);

    const nav = screen.getByRole("navigation", { name: "Sections" });
    await user.click(within(nav).getByRole("link", { name: "Library" }));

    expect(await screen.findByRole("heading", { name: "Library" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Library" })).toHaveAttribute("aria-current", "page");

    // App.tsx's BrowserRouter reads the real jsdom `window.location`, which
    // (unlike MemoryRouter) persists across tests in this file -- navigate
    // back to Design before finishing, same convention the "primary nav
    // links" test above already follows, so the next test's fresh
    // render(<App />) still starts from "/".
    await user.click(within(nav).getByRole("link", { name: "Design" }));
    expect(await screen.findByRole("heading", { name: "Text" })).toBeInTheDocument();
  });

  it("Designer state (the module-level store) survives a round trip through Presets/History", async () => {
    const user = userEvent.setup();
    render(<App />);

    const linesInput = await screen.findByLabelText("Lines 1");
    await user.type(linesInput, "PORT 12");
    await waitFor(() => expect(useDesignerStore.getState().paramsByType.text?.lines).toEqual(["PORT 12"]));

    const nav = screen.getByRole("navigation", { name: "Sections" });
    await user.click(within(nav).getByRole("link", { name: "History" }));
    expect(await screen.findByRole("heading", { name: "History" })).toBeInTheDocument();

    await user.click(within(nav).getByRole("link", { name: "Design" }));
    expect(await screen.findByLabelText("Lines 1")).toHaveValue("PORT 12");
  });

  it("renders HomeBox as a disabled placeholder, not a link, when status reports unconfigured", async () => {
    server.use(
      http.get("/api/homebox/status", () =>
        HttpResponse.json({
          configured: false, reachable: null, healthy: null, version: null, error: null,
        }),
      ),
    );
    render(<App />);

    const nav = screen.getByRole("navigation", { name: "Sections" });
    // The placeholder also renders while status is still LOADING, so a
    // too-eager assertion would pass before the query settles. Anchor on a
    // sibling default-handler query resolving first (the printer badge),
    // by which point the status response has landed too.
    await screen.findByText(/connected/);
    expect(within(nav).queryByRole("link", { name: "HomeBox" })).not.toBeInTheDocument();
    expect(within(nav).getByText("HomeBox")).toHaveAttribute("aria-disabled", "true");
  });
});
