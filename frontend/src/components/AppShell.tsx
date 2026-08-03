import { useState } from "react";
import type { ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { postAuthLogout } from "../api/client";
import type { AuthUser } from "../api/types";
import { ChainPreviewDrawer } from "./ChainPreviewDrawer";
import { GlobalTrayButton, GlobalTrayPanel } from "./GlobalTrayDrawer";
import { PrinterStatusBadge } from "./PrinterStatusBadge";
import { TypeRail } from "./TypeRail";
import { eyebrow, helpText, iconButtonClass, panel, primaryButtonClass, typeHeading } from "./ui/styles";
import { useAuth } from "../hooks/useAuth";
import { useHomeboxStatus } from "../hooks/useHomeboxStatus";
import { useJobEventsContext } from "../hooks/useJobEvents";
import { useTheme } from "../hooks/useTheme";
import type { Theme } from "../hooks/useTheme";

interface AppShellProps {
  children: ReactNode;
}

/** Task 4.1: rendered INSTEAD of the app's own shell whenever
 * `auth_mode === "oidc"` and the session probe (useAuth) reports
 * unauthenticated -- a plain browser navigation to the login route (an
 * `<a href>`, not an onClick handler calling fetch: `/api/auth/login` 302s
 * the WHOLE PAGE to the IdP, which fetch() cannot do -- see api/client.ts's
 * own docstring on this). */
function SignInPanel() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-deck-950 p-6 text-deck-200">
      <div className={`${panel} w-full max-w-sm text-center`}>
        <p className={eyebrow}>Label Studio</p>
        <h1 className={`${typeHeading} mt-2`}>Sign in required</h1>
        <p className={helpText}>This deployment requires signing in before you can use it.</p>
        <a href="/api/auth/login" className={`${primaryButtonClass} mt-6 inline-block`}>
          Sign in
        </a>
      </div>
    </div>
  );
}

/** Task 4.1: the signed-in user's name/email (whichever the IdP actually
 * sent -- either can legitimately be missing depending on the configured
 * `oidc_scopes`) plus a sign-out button, rendered in the header only in
 * oidc mode while authenticated. */
function UserMenu({ user }: { user: AuthUser | null }) {
  const [signingOut, setSigningOut] = useState(false);

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await postAuthLogout();
    } finally {
      // A full reload (not a query-cache invalidation) so every piece of
      // client state -- query cache, zustand stores, the WS connection --
      // starts over clean against the now-signed-out session, same as a
      // real user closing and reopening the tab. Reloading unconditionally
      // (even if the logout call itself failed, e.g. a dropped connection)
      // means the fresh page load's own /auth/me probe is always the
      // final word on whether the session actually ended.
      window.location.reload();
    }
  }

  const label = user?.name ?? user?.email ?? user?.sub ?? "Signed in";

  return (
    <div className="flex items-center gap-2">
      <span className="font-mono text-[11px] text-deck-400" title={user?.email ?? undefined}>
        {label}
      </span>
      <button
        type="button"
        onClick={() => void handleSignOut()}
        disabled={signingOut}
        className="rounded-md border border-deck-600 px-2 py-1 font-condensed text-[11px] font-medium uppercase tracking-wide text-deck-200 transition-colors hover:border-deck-400 disabled:cursor-not-allowed disabled:opacity-60"
      >
        Sign out
      </button>
    </div>
  );
}

const THEME_CYCLE: Theme[] = ["dark", "light", "system"];
const THEME_ICON: Record<Theme, string> = { dark: "●", light: "○", system: "◐" };
const THEME_LABEL: Record<Theme, string> = { dark: "Dark", light: "Light", system: "System" };

/** The header's own compact theme control -- a single icon button cycling
 * dark -> light -> system -> dark (Settings.tsx's "Appearance" section has
 * the full 3-option ui/ThemeToggle.tsx instead) so it costs almost no
 * header width at the 360px floor, unlike a 3-segment control would.
 * `aria-label` announces the CURRENT theme (not what clicking does, which
 * would need updating every click and reads oddly for a toggle) -- the
 * glyph is decorative (`aria-hidden`), same convention as this file's other
 * icon buttons (GlobalTrayDrawer's `×`, TrayItemRow's `↑`/`↓`/`⧉`). */
function ThemeCycleButton() {
  const { theme, setTheme } = useTheme();

  function cycle() {
    const next = THEME_CYCLE[(THEME_CYCLE.indexOf(theme) + 1) % THEME_CYCLE.length]!;
    setTheme(next);
  }

  return (
    <button
      type="button"
      onClick={cycle}
      aria-label={`Theme: ${THEME_LABEL[theme]}`}
      title={`Theme: ${THEME_LABEL[theme]} (click to change)`}
      className={iconButtonClass}
    >
      <span aria-hidden="true">{THEME_ICON[theme]}</span>
    </button>
  );
}

const NAV_LINK_BASE =
  "rounded-md px-3 py-1.5 font-condensed text-[13px] font-medium uppercase tracking-wide transition-colors";

/** `NavLink`'s own render-prop form sets `aria-current="page"` on the
 * active route automatically -- this just supplies the matching visual
 * state (amber, the design doc's one reserved "active" color) instead of
 * every page re-deriving it from `useLocation()` itself. */
function navLinkClass({ isActive }: { isActive: boolean }): string {
  return `${NAV_LINK_BASE} ${isActive ? "bg-amber-500/15 text-amber-300" : "text-deck-200 hover:bg-deck-800"}`;
}

/** App frame per the design doc's layout ASCII: a top STATUS BAR (the
 * instrument readout -- PrinterStatusBadge + the WS event-stream state)
 * and a left TYPES rail (every label type, grouped by category -- see
 * TypeRail) that drives which form Designer renders.
 *
 * Task 2.13: the app's own primary section nav lives here too --
 * Design/Presets/History, real routes (App.tsx wraps this in a
 * BrowserRouter). Task 3.4: `HomeBox` becomes a real NavLink to /homebox
 * once GET /api/homebox/status reports `configured` (useHomeboxStatus) --
 * until then (still loading, or genuinely unconfigured) it stays the
 * disabled, non-interactive placeholder pre-3.4 always was: deliberately
 * not a link at all, so it's never a tab stop that goes nowhere.
 *
 * The TYPES rail only makes sense on the Designer page itself (it drives
 * useDesignerStore.selectedType, which nothing else reads) -- scoped to
 * `pathname === "/"` here rather than rendered on every route.
 *
 * GlobalTrayButton/GlobalTrayPanel (components/GlobalTrayDrawer.tsx), by
 * contrast, mount unconditionally on EVERY route now, including "/" -- the
 * Designer page's own tray UI (components/JobTray.tsx) was retired in favor
 * of sharing this one drawer everywhere; it reads the Designer page's
 * "current, unsaved design" off stores/currentDesign.ts when present (only
 * ever true on "/") and simply has none elsewhere.
 *
 * Track C2 rework: components/ChainPreviewDrawer.tsx mounts here too, on
 * EVERY route just like GlobalTrayButton now does. It's the one right-side
 * slide-over reachable from components/TrayPanel.tsx's own "Preview"
 * button (the SAME TrayPanel instance GlobalTrayPanel renders on every
 * route now), and it must be mounted OUTSIDE GlobalTrayPanel's own
 * translated slide-over wrapper -- see that component's own docstring for
 * why a body portal (ui/Dialog.tsx's own approach) isn't used instead.
 * Dockable-preview feature: it's mounted as the LAST child of the content
 * row's own dock rail below (not a sibling of that row the way it used to
 * be) -- see the inline comment at that mount point for why.
 *
 * Dockable-tray feature: GlobalTrayPanel mounts alongside it, in the SAME
 * dock rail, ABOVE it -- a plain wrapper div, the row's own last child, so
 * that when a user docks BOTH panels at once they stack vertically in one
 * right-hand column (tray on top, preview below) instead of forming two
 * separate side-by-side columns each competing for `<main>`'s width. See
 * the inline comment at that mount point for the exact class contract, and
 * GlobalTrayDrawer.tsx's own docstring for the `xl:max-h-[50%]` height
 * split chosen for the both-docked case.
 *
 * Task 4.1: `useAuth`'s GET /api/auth/me is the ONE probe this gates on --
 * `auth_mode === "none"` (the default) always reports `authenticated: true`
 * (see that route's own docstring), so this branch is a pure no-op in the
 * zero-auth default; only a REAL `oidc` deployment with no valid session
 * ever renders SignInPanel instead of the app below. */
export function AppShell({ children }: AppShellProps) {
  const { connectionState } = useJobEventsContext();
  const { data: homeboxStatus } = useHomeboxStatus();
  const homeboxEnabled = homeboxStatus?.configured === true;
  const { data: auth } = useAuth();
  const { pathname } = useLocation();
  const isDesignRoute = pathname === "/";

  if (auth?.auth_mode === "oidc" && !auth.authenticated) {
    return <SignInPanel />;
  }

  return (
    <div className="flex min-h-screen flex-col bg-deck-950 text-deck-200">
      <header className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-deck-800 bg-deck-900 px-4 py-2.5 sm:px-6">
        <div className="flex items-center gap-2">
          <span aria-hidden className="h-2 w-2 shrink-0 rounded-full bg-amber-500" />
          <span className="font-condensed text-[16px] font-bold uppercase tracking-wide text-deck-200">
            Label Studio
          </span>
        </div>

        <nav aria-label="Sections" className="flex min-w-0 items-center gap-1 overflow-x-auto">
          {homeboxEnabled ? (
            <NavLink to="/homebox" className={navLinkClass}>
              HomeBox
            </NavLink>
          ) : (
            <span
              aria-disabled="true"
              title="HomeBox inventory integration — set HOMEBOX_URL and HOMEBOX_API_KEY to enable it"
              className="cursor-not-allowed select-none rounded-md px-3 py-1.5 font-condensed text-[13px] font-medium uppercase tracking-wide text-deck-600"
            >
              HomeBox
            </span>
          )}
          <NavLink to="/" end className={navLinkClass}>
            Design
          </NavLink>
          <NavLink to="/presets" className={navLinkClass}>
            Presets
          </NavLink>
          <NavLink to="/history" className={navLinkClass}>
            History
          </NavLink>
          <NavLink to="/gallery" className={navLinkClass}>
            Gallery
          </NavLink>
          <NavLink to="/library" className={navLinkClass}>
            Library
          </NavLink>
          <NavLink to="/diagnostics" className={navLinkClass}>
            Diagnostics
          </NavLink>
          <NavLink to="/settings" className={navLinkClass}>
            Settings
          </NavLink>
        </nav>

        <div className="ml-auto flex items-center gap-4">
          <ThemeCycleButton />
          <PrinterStatusBadge />
          {/* The ONE way to reach the tray on every route, including "/" --
              the Designer page no longer mounts its own tray UI (see
              pages/Designer.tsx and stores/currentDesign.ts). Hides itself
              entirely when there's nothing to act on (empty tray AND no
              current design) -- see its own doc. Dockable-tray feature:
              this is now the button HALF of components/GlobalTrayDrawer.tsx
              only -- the panel half mounts separately, in the dock rail
              below, so a docked tray can sit in-flow beside `<main>`
              instead of only ever overlaying it from here. */}
          <GlobalTrayButton />
          <span
            className="font-mono text-[11px] text-deck-400"
            title="Print job event stream"
            data-testid="ws-connection-state"
          >
            {connectionState === "live" ? "live" : connectionState === "reconnecting" ? "reconnecting…" : ""}
          </span>
          {auth?.auth_mode === "oidc" && auth.authenticated ? <UserMenu user={auth.user} /> : null}
        </div>
      </header>

      <div className="flex flex-1 flex-col lg:flex-row lg:items-stretch">
        {isDesignRoute && <TypeRail />}
        <main className="flex-1 overflow-y-auto p-4 sm:p-6">{children}</main>

        {/* Dock rail: the LAST child of the content row, a plain wrapper
            (dockable-tray + dockable-preview features) -- a direct child of
            this row, not nested inside `children`, and not a SIBLING of the
            row the way ChainPreviewDrawer's own mount used to be either.
            Being the row's own last flex item is what lets EITHER panel's
            docked mode (`xl:static ...` class contract, GlobalTrayDrawer.tsx
            and ChainPreviewDrawer.tsx respectively) render as a real
            in-flow right-hand column beside `<main>` -- the row's
            `items-stretch` stretches this wrapper to the same height, same
            as it always stretched ChainPreviewDrawer directly before.
            GlobalTrayPanel mounts FIRST, ChainPreviewDrawer SECOND, so
            when both are docked they stack tray-above-preview in this one
            column (`flex-col`) instead of each fighting for its own
            side-by-side column. No `xl:flex-1`/height split lives here on
            the wrapper itself -- see GlobalTrayDrawer.tsx's own docstring
            for the `xl:max-h-[50%]` chosen on the TRAY panel's own docked
            class string instead (letting the preview panel, unedited, take
            the rest): the wrapper only needs to be a plain flex column, not
            a sizing authority.
            Containing-block check for EITHER panel's undocked (overlay)
            mode `position: fixed`: this wrapper carries no transform/
            filter/backdrop-filter/contain of its own (`flex min-h-0
            flex-col` only), the row it sits in doesn't either, and neither
            does anything between the row and the app root (this
            component's own top-level div, then straight through
            JobEventsProvider/BrowserRouter/QueryClientProvider in App.tsx,
            none of which render a DOM wrapper at all) -- so `fixed` still
            resolves against the viewport here exactly as it did at
            ChainPreviewDrawer's OLD direct mount point (see that
            component's own docstring for why that ancestor check matters
            -- the JobTray translate trap this project hit before).
            On EVERY route, same as GlobalTrayButton above (no
            `isDesignRoute` gate on either). */}
        <div className="flex min-h-0 flex-col">
          <GlobalTrayPanel />
          <ChainPreviewDrawer />
        </div>
      </div>
    </div>
  );
}
