import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { AppShell } from "./AppShell";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";
import { useTrayStore } from "../stores/tray";
import type { LabelDefinition } from "../api/types";

const INITIAL_TRAY_STATE = useTrayStore.getState();

function def(text: string): LabelDefinition {
  return { type: "text", tape: { width_mm: 24, family: "tze" }, params: { lines: [text] } };
}

/** task 4.1: AppShell's own auth gating on top of GET /api/auth/me --
 * every OTHER AppShell/App test in the suite exercises the "none" mode
 * default (test/msw/handlers.ts's authMeNoneHandler), which is the real
 * proof that mode stays a no-op; these two cover the "oidc" branch
 * specifically. */
describe("AppShell auth gating (task 4.1)", () => {
  const originalLocation = window.location;

  afterEach(() => {
    Object.defineProperty(window, "location", { configurable: true, value: originalLocation });
  });

  it("renders a sign-in panel instead of the app when oidc mode reports unauthenticated", async () => {
    server.use(
      http.get("/api/auth/me", () =>
        HttpResponse.json({ auth_mode: "oidc", authenticated: false, user: null }),
      ),
    );

    renderWithProviders(
      <AppShell>
        <div>designer content</div>
      </AppShell>,
    );

    expect(await screen.findByRole("heading", { name: "Sign in required" })).toBeInTheDocument();
    const signInLink = screen.getByRole("link", { name: "Sign in" });
    expect(signInLink).toHaveAttribute("href", "/api/auth/login");

    // The app itself (nav, children) never rendered at all.
    expect(screen.queryByText("designer content")).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Sections" })).not.toBeInTheDocument();
  });

  it("shows the signed-in user's name and a working sign-out button when oidc mode reports authenticated", async () => {
    server.use(
      http.get("/api/auth/me", () =>
        HttpResponse.json({
          auth_mode: "oidc",
          authenticated: true,
          user: { sub: "abc-123", name: "Ada Lovelace", email: "ada@example.com", exp: 9_999_999_999 },
        }),
      ),
    );

    const reloadSpy = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, reload: reloadSpy },
    });

    const user = userEvent.setup();
    renderWithProviders(
      <AppShell>
        <div>designer content</div>
      </AppShell>,
    );

    // The app itself renders normally -- auth doesn't gate anything once
    // authenticated, it just adds the user menu.
    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("designer content")).toBeInTheDocument();

    let logoutCalled = false;
    server.use(
      http.post("/api/auth/logout", () => {
        logoutCalled = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    await user.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => expect(logoutCalled).toBe(true));
    await waitFor(() => expect(reloadSpy).toHaveBeenCalled());
  });
});

/** The TYPES rail (components/TypeRail.tsx) only drives Designer's own
 * useDesignerStore.selectedType -- scoped to the "/" route here rather than
 * rendered (uselessly) on every page. Its complement, GlobalTrayDrawer, is
 * scoped the opposite way: every route EXCEPT "/", since JobTray.tsx
 * already gives the Designer page its own always-visible tray. */
describe("AppShell -- Design-route scoping (type rail + global tray drawer)", () => {
  afterEach(() => {
    useTrayStore.setState(INITIAL_TRAY_STATE, true);
  });

  it("renders the type rail on the Design route, not on other routes", async () => {
    renderWithProviders(
      <AppShell>
        <div>designer content</div>
      </AppShell>,
      { route: "/" },
    );
    expect(await screen.findByRole("navigation", { name: "Label types" })).toBeInTheDocument();
  });

  it("does not render the type rail away from the Design route", async () => {
    renderWithProviders(
      <AppShell>
        <div>history content</div>
      </AppShell>,
      { route: "/history" },
    );
    await screen.findByText("history content");
    expect(screen.queryByRole("navigation", { name: "Label types" })).not.toBeInTheDocument();
  });

  it("hides the global tray drawer button entirely on the Design route (JobTray already covers it there)", async () => {
    useTrayStore.getState().addItem({ definition: def("A"), png: null, lengthMm: 10, label: "Text — A" });

    renderWithProviders(
      <AppShell>
        <div>designer content</div>
      </AppShell>,
      { route: "/" },
    );
    await screen.findByText("designer content");
    expect(screen.queryByRole("button", { name: /^Tray ·/ })).not.toBeInTheDocument();
  });

  it("hides the global tray drawer button when the tray is empty, and shows it once an item is queued", async () => {
    renderWithProviders(
      <AppShell>
        <div>history content</div>
      </AppShell>,
      { route: "/history" },
    );
    await screen.findByText("history content");
    expect(screen.queryByRole("button", { name: /^Tray ·/ })).not.toBeInTheDocument();

    // The store is a module-level zustand singleton (not React context) --
    // GlobalTrayDrawer's own `items` selector reacts to this mutation on its
    // own, with no manual re-render needed (same convention JobTray.test.tsx
    // already relies on for its own store-driven assertions).
    useTrayStore.getState().addItem({ definition: def("A"), png: null, lengthMm: 10, label: "Text — A" });

    expect(await screen.findByRole("button", { name: /^Tray · 1/ })).toBeInTheDocument();
  });

  it("opens the slide-over panel on click, moves focus to its close button, and restores focus to the trigger on Escape", async () => {
    useTrayStore.getState().addItem({ definition: def("A"), png: null, lengthMm: 10, label: "Text — A" });
    const user = userEvent.setup();

    renderWithProviders(
      <AppShell>
        <div>history content</div>
      </AppShell>,
      { route: "/history" },
    );

    const trigger = await screen.findByRole("button", { name: /^Tray · 1/ });
    await user.click(trigger);

    const panel = await screen.findByRole("dialog", { name: "Print tray" });
    const closeButton = screen.getByRole("button", { name: "Close print tray" });
    await waitFor(() => expect(closeButton).toHaveFocus());
    expect(panel).toHaveTextContent("Text — A");

    await user.keyboard("{Escape}");
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});

/** The header's own compact theme control (task 4.4 doc v2) -- an icon
 * button cycling dark -> light -> system -> dark, announcing the CURRENT
 * theme via aria-label (Settings.tsx's own full ThemeToggle covers the
 * radiogroup/keyboard-nav behavior; this only needs to prove the header's
 * OWN wiring -- correct default, cycling, and that it actually flips
 * `<html data-theme>`, the same thing index.css's theme blocks key off). */
describe("AppShell -- compact theme control", () => {
  it("defaults to announcing Dark, and cycles dark -> light -> system -> dark on repeated clicks", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <AppShell>
        <div>designer content</div>
      </AppShell>,
      { route: "/" },
    );

    const button = await screen.findByRole("button", { name: "Theme: Dark" });
    expect(document.documentElement.dataset.theme).toBe("dark");

    await user.click(button);
    expect(await screen.findByRole("button", { name: "Theme: Light" })).toBeInTheDocument();
    expect(document.documentElement.dataset.theme).toBe("light");

    await user.click(screen.getByRole("button", { name: "Theme: Light" }));
    expect(await screen.findByRole("button", { name: "Theme: System" })).toBeInTheDocument();
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);

    await user.click(screen.getByRole("button", { name: "Theme: System" }));
    expect(await screen.findByRole("button", { name: "Theme: Dark" })).toBeInTheDocument();
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
