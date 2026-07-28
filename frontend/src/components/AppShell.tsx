import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { PrinterStatusBadge } from "./PrinterStatusBadge";
import { TypeRail } from "./TypeRail";
import { useJobEventsContext } from "../hooks/useJobEvents";

interface AppShellProps {
  children: ReactNode;
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
 * Design/Presets/History, real routes for the first time (App.tsx now
 * wraps this in a BrowserRouter). `HomeBox` stays a disabled, non-
 * interactive placeholder -- not a general "landing page" but the Phase-3
 * HomeBox inventory integration (docs/research/homebox.md: syncing/
 * printing labels for HomeBox items/locations) -- deliberately not a link
 * at all, so it's never a tab stop that goes nowhere. */
export function AppShell({ children }: AppShellProps) {
  const { connectionState } = useJobEventsContext();

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
          <span
            aria-disabled="true"
            title="HomeBox inventory integration — coming in a future phase"
            className="cursor-not-allowed select-none rounded-md px-3 py-1.5 font-condensed text-[13px] font-medium uppercase tracking-wide text-deck-600"
          >
            HomeBox
          </span>
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
        </div>
      </header>

      <div className="flex flex-1 flex-col lg:flex-row lg:items-stretch">
        <TypeRail />
        <main className="flex-1 overflow-y-auto p-4 sm:p-6">{children}</main>
      </div>
    </div>
  );
}
