import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { AppShell } from "./AppShell";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";
import { usePrintPreviewStore } from "../stores/printPreview";
import { useCurrentDesignStore, type CurrentDesign } from "../stores/currentDesign";
import { useTrayDrawerStore } from "../stores/trayDrawer";
import { useTrayStore } from "../stores/tray";
import { DESKTOP_QUERY } from "../hooks/useIsDesktop";
import { setMediaQueryMatches } from "../test/setup";
import type { LabelDefinition } from "../api/types";

const INITIAL_TRAY_STATE = useTrayStore.getState();
const INITIAL_CHAIN_PREVIEW_STATE = usePrintPreviewStore.getState();
const INITIAL_TRAY_DRAWER_STATE = useTrayDrawerStore.getState();

function def(text: string): LabelDefinition {
  return { type: "text", tape: { width_mm: 24, family: "tze" }, params: { lines: [text] } };
}

function currentDesign(overrides: Partial<CurrentDesign> = {}): CurrentDesign {
  return {
    definition: def("CURRENT"),
    canSubmit: true,
    isRenderable: () => true,
    png: null,
    lengthMm: 25.4,
    label: "Text — CURRENT",
    serializationEnabled: false,
    serialization: null,
    totalLabels: null,
    serializationHasVisibleError: false,
    ...overrides,
  };
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
 * rendered (uselessly) on every page. GlobalTrayDrawer, by contrast, mounts
 * unconditionally on every route now, including "/" -- the Designer page's
 * own tray UI (components/JobTray.tsx) was retired in favor of this same
 * drawer everywhere; see stores/currentDesign.ts for the one thing that
 * still differs by route (the "current, unsaved design" fallback, only
 * ever non-null on "/"). */
describe("AppShell -- Design-route scoping (type rail + global tray drawer)", () => {
  afterEach(() => {
    useTrayStore.setState(INITIAL_TRAY_STATE, true);
    useCurrentDesignStore.setState({ current: null });
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

  it("shows the global tray drawer button on the Design route too, now that the tray is unified there", async () => {
    useTrayStore.getState().addItem({ definition: def("A"), png: null, lengthMm: 10, label: "Text — A" });

    renderWithProviders(
      <AppShell>
        <div>designer content</div>
      </AppShell>,
      { route: "/" },
    );
    await screen.findByText("designer content");
    expect(await screen.findByRole("button", { name: /^Tray · 1/ })).toBeInTheDocument();
  });

  it("on the Design route with an empty tray but a seeded current design, shows a plain 'Tray' button (never 'Tray · 0')", async () => {
    useCurrentDesignStore.setState({ current: currentDesign() });

    renderWithProviders(
      <AppShell>
        <div>designer content</div>
      </AppShell>,
      { route: "/" },
    );
    await screen.findByText("designer content");
    expect(await screen.findByRole("button", { name: "Tray" })).toBeInTheDocument();
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

/** The two panels don't share one rail column. GlobalTrayDrawer.tsx's own
 * `xl:static` in-flow-column class contract still needs the tray panel to
 * be an actual flex ITEM of a column that is ITSELF a flex item of
 * AppShell's content row (the div holding TypeRail + the middle column that
 * wraps `<main>`) -- a sibling of that row could never reflow `<main>`
 * beside it no matter what classes the panel itself carried.
 * PrintPreviewDeck.tsx, by contrast, mounts as the LAST child of that middle
 * column -- a sibling of `<main>`, NOT of the tray rail, and no longer a
 * root-level sibling of the whole content row at all (a prior bug: mounting
 * it there took its `xl:h-64` out of the content row's own flex budget,
 * which shortened the tray rail beside it too, every time it opened). Its
 * own `xl:static xl:h-64` bottom-deck contract now spans the middle
 * column's width (the viewport minus TypeRail and the tray rail when either
 * is visible) instead of the full browser viewport, and its `xl:h-64`
 * shrinks ONLY `<main>` -- the tray rail, a separate flex item of the
 * content row, never resizes when the deck opens or closes. This proves the
 * DOM shape AppShell.tsx's own docstring documents, independent of either
 * panel's own in-flow-vs-modal rendering (covered by
 * GlobalTrayDrawer.test.tsx/PrintPreviewDeck.test.tsx themselves). */
describe("AppShell -- tray-only rail, and the preview deck nested in the middle column beside <main>", () => {
  afterEach(() => {
    useTrayStore.setState(INITIAL_TRAY_STATE, true);
    usePrintPreviewStore.setState(INITIAL_CHAIN_PREVIEW_STATE, true);
    useTrayDrawerStore.setState(INITIAL_TRAY_DRAWER_STATE, true);
  });

  it("mounts the tray panel inside a rail that is a child of the content row, a sibling of the middle column that holds <main>, holding no other panel", async () => {
    renderWithProviders(
      <AppShell>
        <div>designer content</div>
      </AppShell>,
      { route: "/" },
    );
    await screen.findByText("designer content");

    // GlobalTrayPanel returns a Fragment (no wrapping DOM node of its own),
    // so its real DOM parent is whichever element renders it as JSX --
    // AppShell's own rail div.
    const trayPanel = screen.getByTestId("global-tray-drawer-panel");
    const dockRail = trayPanel.parentElement;
    expect(dockRail).not.toBeNull();
    // The preview deck no longer shares this rail -- see the describe
    // block's own docstring.
    expect(within(dockRail!).queryByTestId("print-preview-deck-panel")).not.toBeInTheDocument();
    // Viewport-bound frame (Opus review fix): the rail carries no explicit
    // height, sticky, or calc() of its own anymore -- the ROOT column below
    // is `h-screen`, and the content row's own `items-stretch` sizes this
    // wrapper to match exactly, regardless of the header's own (variable)
    // height or whether the preview deck is open (see the next test).
    expect(dockRail?.className).toBe("flex min-h-0 flex-col");
    // No transform/filter of its own -- see AppShell.tsx's own inline
    // comment at this mount point for why that matters to the tray panel's
    // below-`xl` `position: fixed` overlay.
    expect(dockRail?.className).not.toMatch(/transform|filter/);

    const contentRow = dockRail?.parentElement;
    expect(contentRow).not.toBeNull();
    expect(contentRow?.className).toContain("lg:flex-row");
    expect(contentRow?.className).toContain("items-stretch");

    // The root column is what actually owns the viewport-bound height now
    // (`h-screen`, not `min-h-screen`) -- see AppShell.tsx's own
    // top-of-file docstring for why that's what lets flexbox alone divide
    // the frame between the header, this row, and the preview deck nested
    // below.
    const rootColumn = contentRow?.parentElement;
    expect(rootColumn).not.toBeNull();
    const rootClasses = rootColumn?.className.split(" ") ?? [];
    expect(rootClasses).toContain("h-screen");
    expect(rootClasses).not.toContain("min-h-screen");

    // `<main>` now lives inside a middle column of its own -- a sibling of
    // the rail within the content row, not a direct child of the row
    // itself (that middle column is where the preview deck mounts too, see
    // the next test).
    const main = screen.getByText("designer content").closest("main");
    expect(main).not.toBeNull();
    const middleColumn = main?.parentElement;
    expect(middleColumn).not.toBeNull();
    expect(middleColumn).not.toBe(dockRail);
    expect(middleColumn?.parentElement).toBe(contentRow);
  });

  it("mounts the preview deck panel inside the middle column that holds <main> -- a sibling of <main> and that column's own last child, never a sibling of the tray rail", async () => {
    renderWithProviders(
      <AppShell>
        <div>designer content</div>
      </AppShell>,
      { route: "/" },
    );
    await screen.findByText("designer content");

    const trayPanel = screen.getByTestId("global-tray-drawer-panel");
    const dockRail = trayPanel.parentElement!;
    const contentRow = dockRail.parentElement!;

    const main = screen.getByText("designer content").closest("main")!;
    const middleColumn = main.parentElement!;
    expect(middleColumn.parentElement).toBe(contentRow);

    const deckPanel = screen.getByTestId("print-preview-deck-panel");
    // Same parent as <main> -- NOT the tray rail, and NOT the content row
    // itself (the deck's old root-level mount point, before this fix).
    expect(deckPanel.parentElement).toBe(middleColumn);
    expect(deckPanel.parentElement).not.toBe(dockRail);
    expect(deckPanel.parentElement).not.toBe(contentRow);

    // Comes after <main> among the middle column's own children -- the
    // deck is that column's LAST child.
    const columnChildren = Array.from(middleColumn.children);
    expect(columnChildren.indexOf(main)).toBeLessThan(columnChildren.indexOf(deckPanel));
  });

  it("the tray rail's class contract does not change when the preview deck is open -- the two panels are fully decoupled now", async () => {
    renderWithProviders(
      <AppShell>
        <div>designer content</div>
      </AppShell>,
      { route: "/" },
    );
    await screen.findByText("designer content");

    const trayPanel = screen.getByTestId("global-tray-drawer-panel");
    const dockRail = trayPanel.parentElement!;
    const beforeClassName = dockRail.className;
    expect(beforeClassName).toBe("flex min-h-0 flex-col");

    // Docking (and opening) the preview deck used to shrink this rail's own
    // pinned height via a cross-file calc() -- the mechanism the Opus
    // review found geometrically broken (the header's own variable height
    // made the reserved figure wrong) and this fix removed entirely. The
    // rail's class string must stay untouched by the preview deck's own
    // store state now that flexbox (not calc) owns the geometry.
    usePrintPreviewStore.setState({ open: true });
    await waitFor(() => expect(usePrintPreviewStore.getState().open).toBe(true));
    expect(dockRail.className).toBe(beforeClassName);
  });

  it("with the preview deck open, the rail stays a direct child of the content row and the deck stays out of that row entirely -- they never become siblings", async () => {
    usePrintPreviewStore.setState({ open: true });

    renderWithProviders(
      <AppShell>
        <div>designer content</div>
      </AppShell>,
      { route: "/" },
    );
    await screen.findByText("designer content");

    const trayPanel = screen.getByTestId("global-tray-drawer-panel");
    const dockRail = trayPanel.parentElement!;
    const contentRow = dockRail.parentElement!;

    // The rail is still a direct child of the content row...
    expect(Array.from(contentRow.children)).toContain(dockRail);

    // ...and the (now open) deck still isn't: it's nested one level down,
    // inside the middle column beside <main>, regardless of `open` -- this
    // is the geometry fix itself, expressed as a DOM assertion rather than
    // a visual one.
    const deckPanel = screen.getByTestId("print-preview-deck-panel");
    expect(deckPanel.parentElement).not.toBe(contentRow);
    expect(Array.from(contentRow.children)).not.toContain(deckPanel);
  });

  it("open at `xl`, the preview deck panel carries the in-flow bottom-deck class contract (static/h-64/full-width), not sticky and not the old right-column width", async () => {
    setMediaQueryMatches(DESKTOP_QUERY, true);
    usePrintPreviewStore.setState({ open: true });

    renderWithProviders(
      <AppShell>
        <div>designer content</div>
      </AppShell>,
      { route: "/" },
    );
    await screen.findByText("designer content");

    const deckPanel = await screen.findByRole("complementary", { name: "Print preview" });
    expect(deckPanel.className).toContain("xl:static");
    expect(deckPanel.className).toContain("xl:h-64");
    expect(deckPanel.className).toContain("xl:w-full");
    expect(deckPanel.className).not.toContain("xl:sticky");
    expect(deckPanel.className).not.toContain("xl:bottom-0");
    expect(deckPanel.className).not.toContain("xl:w-[26rem]");
  });
});
