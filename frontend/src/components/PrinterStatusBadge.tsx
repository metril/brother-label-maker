import { usePrinterStatus } from "../hooks/usePrinterStatus";

interface DotProps {
  colorClass: string;
}

function Dot({ colorClass }: DotProps) {
  return <span aria-hidden className={`h-2 w-2 shrink-0 rounded-full ${colorClass}`} />;
}

/** Top-bar printer connectivity readout: a dot + short text (connected +
 * media width, or the error string), plus a "mock" tag when the backend is
 * running in mock printer mode (config.py's AppConfig.printer_mode). */
export function PrinterStatusBadge() {
  const { data, isLoading, isError } = usePrinterStatus();

  let dotClass = "bg-ink-500";
  let label = "checking…";

  if (!isLoading) {
    if (isError || !data) {
      dotClass = "bg-red-500";
      label = "unreachable";
    } else if (!data.connected) {
      dotClass = "bg-red-500";
      label = data.error ?? "disconnected";
    } else {
      dotClass = "bg-emerald-500";
      const widthMm = data.status?.media_width_mm;
      label = widthMm != null ? `${widthMm}mm` : "connected";
    }
  }

  return (
    <div
      role="status"
      aria-label="Printer status"
      className="flex items-center gap-2 rounded-md border border-ink-700 bg-ink-900 px-2.5 py-1.5 text-xs text-ink-200"
    >
      <Dot colorClass={dotClass} />
      <span>{label}</span>
      {data?.printer_mode === "mock" && (
        <span className="rounded border border-ink-600 px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-400">
          mock
        </span>
      )}
    </div>
  );
}
