import { useState } from "react";
import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { postAuthLogout } from "../api/client";
import type { AuthUser } from "../api/types";
import { PrinterStatusBadge } from "./PrinterStatusBadge";
import { TypeRail } from "./TypeRail";
import { eyebrow, helpText, panel, primaryButtonClass, typeHeading } from "./ui/styles";
import { useAuth } from "../hooks/useAuth";
import { useHomeboxStatus } from "../hooks/useHomeboxStatus";
import { useJobEventsContext } from "../hooks/useJobEvents";

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

        <nav aria-label="Sections" className="flex items-center gap-1">
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
          <NavLink to="/diagnostics" className={navLinkClass}>
            Diagnostics
          </NavLink>
          <NavLink to="/settings" className={navLinkClass}>
            Settings
          </NavLink>
        </nav>

        <div className="ml-auto flex items-center gap-4">
          <PrinterStatusBadge />
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
        <TypeRail />
        <main className="flex-1 overflow-y-auto p-4 sm:p-6">{children}</main>
      </div>
    </div>
  );
}
