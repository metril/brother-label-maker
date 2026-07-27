import type { ReactNode } from "react";
import { usePrinterStatus } from "../hooks/usePrinterStatus";
import { describeMedia } from "../lib/printerStatus";
import { Pending } from "./ui/Pending";

interface DotProps {
  colorClass: string;
}

function Dot({ colorClass }: DotProps) {
  return <span aria-hidden className={`h-2 w-2 shrink-0 rounded-full ${colorClass}`} />;
}

/** Status bar's instrument readout: connected dot (sage/rust -- never
 * amber, that's reserved for the primary accent) + "connected · 24mm TZe ·
 * laminated" in JetBrains Mono, plus a "mock" tag when the backend is
 * running in mock printer mode (config.py's AppConfig.printer_mode). */
export function PrinterStatusBadge() {
  const { data, isLoading, isError } = usePrinterStatus();

  let dotClass = "bg-deck-400";
  let label: ReactNode = <Pending />;

  if (!isLoading) {
    if (isError || !data) {
      dotClass = "bg-rust-500";
      label = "unreachable";
    } else if (!data.connected) {
      dotClass = "bg-rust-500";
      label = data.error ?? "disconnected";
    } else {
      dotClass = "bg-sage-400";
      const media = describeMedia(data.status);
      label = media ? `connected · ${media}` : "connected";
    }
  }

  return (
    <div role="status" aria-label="Printer status" className="flex items-center gap-2 font-mono text-[12px] text-deck-200">
      <Dot colorClass={dotClass} />
      <span>{label}</span>
      {data?.printer_mode === "mock" && (
        <span className="rounded border border-deck-600 px-1.5 py-0.5 font-condensed text-[10px] font-bold uppercase tracking-wide text-amber-300">
          mock
        </span>
      )}
    </div>
  );
}
