// Pure helpers for task 2.12's job tray (stores/tray.ts, components/JobTray.tsx,
// components/TrayItemRow.tsx) -- kept UI-framework-free so id generation and
// the short-label heuristic are independently unit-testable, mirroring
// lib/sequence.ts's own split between pure logic and the components that
// render it.

import { firstTextFieldValue } from "./sequence";
import type { JsonSchemaObject } from "../schema/jsonSchema";

/** A short, stable-enough id for a client-only tray item (never sent to the
 * server -- TrayItem.id exists purely for React keys and up/down/remove/
 * duplicate targeting). `crypto.randomUUID` is available in every browser
 * this app targets (and in the Vitest/Node test environment); the fallback
 * only matters for an exotic runtime that somehow lacks it. */
export function nextTrayItemId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `tray-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** "Add to tray"'s short display label: the type's own title, plus the
 * first non-blank text content the label actually carries (schema/params-
 * order -- reuses lib/sequence.ts's firstTextFieldValue, the SAME "what's
 * the representative text" heuristic task 2.11 already built for the
 * serialization sample chips) -- e.g. "Patch Panel — UPLINK-A". Falls back
 * to just the type title when nothing qualifies (e.g. a patch_panel whose
 * blocks are all still blank). */
export function describeCurrentDesign(
  typeTitle: string,
  schema: JsonSchemaObject,
  params: Record<string, unknown>,
): string {
  const text = firstTextFieldValue(schema, params).trim();
  return text === "" ? typeTitle : `${typeTitle} — ${truncate(text, 40)}`;
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}
