import type { ReactNode } from "react";
import { PrinterStatusBadge } from "./PrinterStatusBadge";
import { TypeRail } from "./TypeRail";
import { useJobEventsContext } from "../hooks/useJobEvents";

interface AppShellProps {
  children: ReactNode;
}

/** App frame per the design doc's layout ASCII: a top STATUS BAR (the
 * instrument readout -- PrinterStatusBadge + the WS event-stream state)
 * and a left TYPES rail (the 9 label types, grouped by category -- see
 * TypeRail) that drives which form Designer renders. Designer is still the
 * only real route (no router yet -- single page + shell), so the rail
 * lives here rather than duplicated per-page. */
export function AppShell({ children }: AppShellProps) {
  const { connectionState } = useJobEventsContext();

  return (
    <div className="flex min-h-screen flex-col bg-deck-950 text-deck-200">
      <header className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-deck-800 bg-deck-900 px-4 py-2.5 sm:px-6">
        <div className="flex items-center gap-2">
          <span aria-hidden className="h-2 w-2 shrink-0 rounded-full bg-amber-500" />
          <span className="font-condensed text-[16px] font-bold uppercase tracking-wide text-deck-200">
            Label Studio
          </span>
        </div>
        <div className="flex items-center gap-4">
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
