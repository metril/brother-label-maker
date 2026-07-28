import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { AppShell } from "./AppShell";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";

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
