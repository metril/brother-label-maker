import type { JobStatus } from "../api/types";

const STATUS_LABEL: Record<JobStatus, string> = {
  queued: "Queued",
  printing: "Printing",
  done: "Done",
  failed: "Failed",
  canceled: "Canceled",
};

// Design doc's semantic colors: sage for success, rust for errors/
// destructive, amber reserved for the ONE active/primary accent -- queued
// (nothing happening yet) stays plain graphite.
const STATUS_CLASS: Record<JobStatus, string> = {
  queued: "border-deck-600 bg-deck-800 text-deck-400",
  printing: "border-amber-500 bg-amber-500/15 text-amber-300",
  done: "border-sage-400 bg-sage-400/15 text-sage-400",
  failed: "border-rust-500 bg-rust-500/15 text-rust-500",
  canceled: "border-rust-500 bg-rust-500/10 text-rust-500",
};

interface StatusChipProps {
  status: JobStatus;
  className?: string;
}

/** A small pill in the design system's semantic status colors -- shared by
 * History's rows and Presets' inline "print this preset" feedback (both
 * track a print job's lifecycle through the same WS event stream,
 * hooks/useJobEvents.ts). Status-to-event mapping lives in lib/jobStatus.ts
 * (kept out of this file so it exports only the component, per
 * react-refresh's only-export-components rule). */
export function StatusChip({ status, className }: StatusChipProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 font-mono text-[11px] uppercase tracking-wide ${STATUS_CLASS[status]} ${className ?? ""}`}
    >
      {STATUS_LABEL[status]}
    </span>
  );
}
