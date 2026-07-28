// Pure helpers for task 2.13's live job-status overlay (components/
// StatusChip.tsx, pages/History.tsx, components/PresetCard.tsx) -- kept
// UI-framework-free per this app's own convention (see lib/tray.ts,
// lib/sequence.ts), and split out of StatusChip.tsx itself so that
// component file exports ONLY the component (react-refresh's
// only-export-components rule).

import type { JobEventType, JobStatus } from "../api/types";

/** Maps the latest WS `job.*` event for a job onto the JobStatus it implies
 * -- used to overlay a LIVE status on top of a possibly-stale server-
 * fetched one (History's rows; Presets'/History's own "print/reprint this"
 * inline feedback) without waiting for a refetch. `job.queued`/
 * `job.started`/`job.progress` all mean "not finished yet" from the
 * caller's point of view; only the three terminal events change the
 * OUTCOME. */
export function statusFromEvent(eventType: JobEventType): JobStatus {
  switch (eventType) {
    case "job.done":
      return "done";
    case "job.failed":
      return "failed";
    case "job.canceled":
      return "canceled";
    case "job.started":
    case "job.progress":
      return "printing";
    case "job.queued":
    default:
      return "queued";
  }
}

/** True for the three OUTCOME events (done/failed/canceled) -- the ones
 * that mean a tracked job's row is stale and worth refetching for real
 * (fresh tape_used_mm/thumbnail_url, or -- for a reprint -- the NEW job's
 * own row appearing at all). `job.queued`/`job.started`/`job.progress` are
 * all "still in flight", nothing to invalidate for yet. */
export function isTerminalEventType(eventType: JobEventType): boolean {
  return eventType === "job.done" || eventType === "job.failed" || eventType === "job.canceled";
}
