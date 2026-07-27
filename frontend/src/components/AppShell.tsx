import type { ReactNode } from "react";
import { PrinterStatusBadge } from "./PrinterStatusBadge";
import { useJobEventsContext } from "../hooks/useJobEvents";

const DISABLED_NAV_ITEMS = ["Presets", "History", "HomeBox"];

interface AppShellProps {
  children: ReactNode;
}

/** App frame: left nav (Designer is the only live route today -- no router
 * yet, single page + shell), top bar with the printer status badge. */
export function AppShell({ children }: AppShellProps) {
  const { connectionState } = useJobEventsContext();

  return (
    <div className="flex min-h-screen bg-ink-950 text-ink-100">
      <nav className="flex w-48 shrink-0 flex-col gap-1 border-r border-ink-800 bg-ink-900 p-4">
        <div className="mb-4 flex items-center gap-2 px-1">
          <span className="h-2 w-2 rounded-full bg-amber-500" />
          <span className="text-sm font-semibold tracking-wide text-ink-100">Label Studio</span>
        </div>

        <span className="rounded-md bg-amber-950 px-3 py-2 text-sm font-medium text-amber-300">
          Designer
        </span>

        {DISABLED_NAV_ITEMS.map((label) => (
          <span
            key={label}
            aria-disabled="true"
            title="Coming soon"
            className="flex items-center justify-between rounded-md px-3 py-2 text-sm text-ink-500"
          >
            {label}
            <span className="text-[10px] uppercase tracking-wide text-ink-600">soon</span>
          </span>
        ))}
      </nav>

      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-ink-800 bg-ink-900/60 px-6 py-3">
          <h1 className="text-sm font-medium text-ink-300">PT-E720BT Label Studio</h1>
          <div className="flex items-center gap-3">
            <span
              className="text-[11px] text-ink-500"
              title="Print job event stream"
              data-testid="ws-connection-state"
            >
              {connectionState === "live" ? "live" : connectionState === "reconnecting" ? "reconnecting…" : ""}
            </span>
            <PrinterStatusBadge />
          </div>
        </header>
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}
