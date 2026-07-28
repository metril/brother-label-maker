// Pure helpers for the History page (pages/History.tsx,
// components/HistoryDetailsDialog.tsx) -- kept UI-framework-free per this
// app's own convention (see lib/tray.ts, lib/sequence.ts).

import type { LabelDefinition } from "../api/types";

/** A print job's stored `definition` (GET /api/history/{id}, same full
 * shape as GET /api/print/jobs/{id}) is the FULL PrintRequest that was
 * submitted -- `{labels, options?, serialization?}` (router_print.py's
 * create_print_job stores `request.model_dump(mode="json")` verbatim) --
 * NOT a single LabelDefinition. "Load into designer" (task 2.13's brief)
 * only makes sense for a job that was a single, un-serialized label:
 * exactly one entry in `labels` and no `serialization`. Returns null for
 * anything else (a tray print of several labels, a serialized run, or a
 * shape this doesn't recognize at all -- `definition` is `unknown` at this
 * layer, same caution as api/types.ts's own PrintJob.definition). */
export function extractSingleLabel(definition: unknown): LabelDefinition | null {
  if (definition === null || typeof definition !== "object") return null;
  const body = definition as { labels?: unknown; serialization?: unknown };
  if (body.serialization != null) return null;
  if (!Array.isArray(body.labels) || body.labels.length !== 1) return null;

  const label = body.labels[0];
  if (label === null || typeof label !== "object") return null;
  const candidate = label as Partial<LabelDefinition>;
  if (typeof candidate.type !== "string") return null;
  if (candidate.params === null || typeof candidate.params !== "object") return null;
  if (candidate.tape === null || typeof candidate.tape !== "object") return null;

  return candidate as LabelDefinition;
}
