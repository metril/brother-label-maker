// Pure helpers for task 2.11's serialization editor -- BarTender-model
// sequences (see backend/render/serialize.py's module docstring for the
// full expansion model). Kept UI-framework-free (no React) so bounds
// checking, list/CSV parsing, and the collation-pattern demo are all
// independently unit-testable, mirroring schema/numberValidity.ts's own
// split between "pure validation logic" and the components that render it.

import { classifyField, resolveRef, splitNullable, type JsonSchemaObject } from "../schema/jsonSchema";
import type { Collation, Sequence, SequenceKind } from "../api/types";

/** A sensible starting Sequence -- mirrors backend/render/serialize.py's
 * own Field(...) defaults exactly (kind excepted, which has no server
 * default since it's required; "numeric" is this UI's own starting pick). */
export const DEFAULT_SEQUENCE: Sequence = {
  kind: "numeric",
  count: 1,
  copies_per_value: 1,
  collation: "copies_adjacent",
  start: 1,
  step: 1,
  pad_width: 0,
  alpha_start: "A",
  values: [],
  rows: [],
};

export const SEQUENCE_KIND_OPTIONS: { value: SequenceKind; label: string }[] = [
  { value: "numeric", label: "Numbers" },
  { value: "alpha", label: "Letters" },
  { value: "list", label: "List" },
  { value: "csv", label: "CSV" },
];

/** The number of DISTINCT values `seq` produces -- mirrors backend/render/
 * serialize.py's effective_count() exactly (seq.count for numeric/alpha,
 * or values.length/rows.length for list/csv, whose own `count` is unused). */
export function effectiveCount(seq: Sequence): number {
  if (seq.kind === "numeric" || seq.kind === "alpha") return seq.count ?? 1;
  if (seq.kind === "list") return (seq.values ?? []).length;
  return (seq.rows ?? []).length;
}

/** effectiveCount(seq) * copies_per_value -- mirrors serialize.py's
 * total_labels(). Purely arithmetic (no server round-trip needed), but the
 * AUTHORITATIVE "is this actually printable" answer -- including the 1000-
 * label cap and ALPHA overflow -- still comes from POST /api/render/expand
 * (see hooks/useSequenceExpand.ts): this is just the number, not a
 * validity claim. */
export function sequenceTotalLabels(seq: Sequence): number {
  return effectiveCount(seq) * (seq.copies_per_value ?? 1);
}

export interface SequenceFieldErrors {
  count?: string;
  copiesPerValue?: string;
  start?: string;
  step?: string;
  padWidth?: string;
  alphaStart?: string;
  values?: string;
  rows?: string;
}

/** Client-side bounds checks mirroring Sequence's own per-field Field(...)
 * constraints (backend/render/serialize.py) -- instant, no debounce, no
 * network round-trip, exactly like schema/numberValidity.ts's own per-
 * field checks for the params form. Deliberately does NOT replicate the
 * cross-field checks (the 1000-label total cap, ALPHA under/overflow past
 * 'A'/'ZZZ') -- those are left to the server's own readable 422 (see
 * useSequenceExpand.ts), same "don't re-implement every server-side rule
 * client-side" philosophy numberValidity.ts's own docstring describes for
 * breaker_box's cross-field parity check. */
export function validateSequence(seq: Sequence): SequenceFieldErrors {
  const errors: SequenceFieldErrors = {};

  const copies = seq.copies_per_value;
  if (copies === undefined || !Number.isInteger(copies) || copies < 1 || copies > 100) {
    errors.copiesPerValue = "must be a whole number between 1 and 100";
  }

  if (seq.kind === "numeric" || seq.kind === "alpha") {
    const count = seq.count;
    if (count === undefined || !Number.isInteger(count) || count < 1 || count > 500) {
      errors.count = "must be a whole number between 1 and 500";
    }
    const step = seq.step;
    if (step === undefined || !Number.isInteger(step)) {
      errors.step = "enter a whole number";
    } else if (step === 0) {
      errors.step = "step must not be 0";
    } else if (step < -9999 || step > 9999) {
      errors.step = "must be between -9999 and 9999";
    }
  }

  if (seq.kind === "numeric") {
    const pad = seq.pad_width;
    if (pad === undefined || !Number.isInteger(pad) || pad < 0 || pad > 6) {
      errors.padWidth = "must be a whole number between 0 and 6";
    }
    const start = seq.start;
    if (start === undefined || !Number.isInteger(start) || start < -999999 || start > 999999) {
      errors.start = "must be a whole number between -999999 and 999999";
    }
  }

  if (seq.kind === "alpha") {
    const alphaStart = seq.alpha_start ?? "";
    if (!/^[A-Z]{1,3}$/.test(alphaStart)) {
      errors.alphaStart = "1-3 letters, A-Z only";
    }
  }

  if (seq.kind === "list") {
    const values = (seq.values ?? []).filter((v) => v.trim() !== "");
    if (values.length === 0) {
      errors.values = "add at least one value";
    } else if (values.length > 500) {
      errors.values = "at most 500 values";
    }
  }

  if (seq.kind === "csv") {
    if ((seq.rows ?? []).length === 0) {
      errors.rows = "upload a CSV file";
    }
  }

  return errors;
}

export function hasSequenceFieldError(seq: Sequence): boolean {
  return Object.keys(validateSequence(seq)).length > 0;
}

/** The List kind's textarea (one value per line) -> Sequence.values: trims
 * each line, drops blank ones entirely -- a blank line carries no serial
 * value to print. The textarea's own DISPLAYED text is kept as separate
 * local component state (never re-derived from this parsed result), so a
 * blank line the user is mid-typing-past doesn't vanish out from under
 * them -- see components/SequenceEditor.tsx's ListValuesField. */
export function parseListTextarea(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

/** Column names of an uploaded CSV's rows, in their original order -- POST
 * /api/serialize/csv's own `columns` field already carries this, but once
 * rows live on Sequence.rows alone this recovers the same order from the
 * rows themselves (JS preserves string-key insertion order, and every row
 * shares identical columns -- enforced server-side at upload time). */
export function csvColumns(rows: Record<string, string>[]): string[] {
  return rows.length > 0 ? Object.keys(rows[0]!) : [];
}

/** The FIRST field in `schema` (its own declared order) that carries real,
 * non-blank text content right now -- string fields read directly, array-
 * of-string fields read their first non-blank entry, array-of-OBJECT
 * fields (patch_panel's `blocks`, breaker_box's `breakers`, ...) recurse
 * into each item in turn using this SAME function against the item's own
 * schema+params (so e.g. a block's `lines` is found exactly the way a
 * top-level `lines` field would be). Feeds POST /api/render/expand's
 * `sample` (see useSequenceExpand.ts) so the live value chips can show real
 * token substitution ("PORT-{seq}" -> "PORT-01") for whichever field the
 * user is actually likely to serialize, and lib/tray.ts's
 * describeCurrentDesign (task 2.12's tray-item captions) -- deliberately
 * NOT necessarily the schema's literal first property (several types lead
 * with a number field, e.g. patch_panel's block_length_mm) and NOT a
 * currently-blank field (which would just demo as empty, or -- for a tray
 * caption -- silently skip straight to an unrelated later field, e.g.
 * font_family, and caption a patch panel "Patch Panel — Inter"; confirmed
 * live before this recursion was added). Returns "" when nothing qualifies
 * (e.g. patch_panel before any block has text) -- callers fall back to
 * showing raw sequence values (or just the type name) in that case. */
export function firstTextFieldValue(schema: JsonSchemaObject, params: Record<string, unknown>): string {
  for (const [key, propSchema] of Object.entries(schema.properties ?? {})) {
    const { inner } = splitNullable(propSchema, schema);
    const resolved = resolveRef(inner, schema);
    const kind = classifyField(resolved);
    if (kind === "string") {
      const value = params[key];
      if (typeof value === "string" && value.trim() !== "") return value;
    } else if (kind === "array-string") {
      const value = params[key];
      if (Array.isArray(value)) {
        const first = value.find((v) => typeof v === "string" && v.trim() !== "");
        if (typeof first === "string") return first;
      }
    } else if (kind === "array-object") {
      const value = params[key];
      if (Array.isArray(value)) {
        const itemSchema = resolveRef(resolved.items ?? {}, schema);
        for (const item of value) {
          if (item === null || typeof item !== "object") continue;
          const found = firstTextFieldValue(itemSchema, item as Record<string, unknown>);
          if (found !== "") return found;
        }
      }
    }
  }
  return "";
}

export interface CollationPatternResult {
  pattern: string[];
  more: number;
}

/** The copies_per_value x collation ordering demo for the Serialize
 * panel's own explainer ("A A B B" vs "A B A B", but with the CURRENT
 * real values, not literal letters) -- mirrors backend/render/serialize.
 * py's _ordered_pairs ordering exactly, applied to a small slice of the
 * current distinct values (never the full run: this is a "what does the
 * ordering look like" explainer, not the live-chips section, which shows
 * the real, separately-capped-at-24 expansion via /api/render/expand). */
export function collationPattern(values: string[], copiesPerValue: number, collation: Collation): CollationPatternResult {
  const distinct = values.slice(0, 6);
  const copies = Math.max(1, Math.min(Math.trunc(copiesPerValue) || 1, 100));
  const full =
    collation === "sequence_repeated"
      ? Array.from({ length: copies }, () => distinct).flat()
      : distinct.flatMap((v) => Array.from({ length: copies }, () => v));
  const pattern = full.slice(0, 24);
  return { pattern, more: full.length - pattern.length };
}
