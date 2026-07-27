import { create } from "zustand";
import type { LabelDefinition, Tape, TapeFamily } from "../api/types";
import { buildDefaultParams } from "../schema/defaults";
import type { JsonSchemaObject } from "../schema/jsonSchema";

// Was a text-only store (setLine/addLine/setFontFamily/... one setter per
// TextLabelParams field) through task 2.9 -- task 2.10's schema-driven form
// engine covers all 9 label types with ONE generic setParams, so the store
// only needs to remember: which tape, which type is selected, and each
// type's own params (kept PER TYPE, not just for the active one, so
// switching from "text" to "barcode" and back doesn't lose what you typed).

interface DesignerState {
  tape: Tape;
  selectedType: string | null;
  paramsByType: Record<string, Record<string, unknown>>;

  setTapeWidthMm: (widthMm: number) => void;
  setTapeFamily: (family: TapeFamily) => void;
  /** Makes `type` the active type, seeding its params from `schema`'s own
   * defaults (schema/defaults.ts) the FIRST time it's selected -- a later
   * re-selection (switching back to a type visited earlier this session)
   * keeps whatever was already there. */
  selectType: (type: string, schema: JsonSchemaObject) => void;
  setParams: (type: string, params: Record<string, unknown>) => void;
}

export const useDesignerStore = create<DesignerState>((set) => ({
  tape: { width_mm: 24, family: "tze" },
  selectedType: null,
  paramsByType: {},

  setTapeWidthMm: (widthMm) => set((state) => ({ tape: { ...state.tape, width_mm: widthMm } })),

  setTapeFamily: (family) => set((state) => ({ tape: { ...state.tape, family } })),

  selectType: (type, schema) =>
    set((state) => {
      if (state.paramsByType[type]) return { selectedType: type };
      return {
        selectedType: type,
        paramsByType: { ...state.paramsByType, [type]: buildDefaultParams(schema) },
      };
    }),

  setParams: (type, params) =>
    set((state) => ({ paramsByType: { ...state.paramsByType, [type]: params } })),
}));

export function buildDefinition(type: string, tape: Tape, params: Record<string, unknown>): LabelDefinition {
  return { type, tape, params };
}

/** I1: tape-mismatch preflight guardrail message, or null when there's
 * nothing to warn about (disconnected, the printer's loaded width isn't
 * known yet, or it matches the design). A WARNING, never a hard block --
 * printer/status can be stale (usePrinterStatus polls every 10s), so this
 * is only a banner; the backend still re-checks against the printer's live
 * status at print time and fails the job with the same friendly wording if
 * it's really wrong (see jobs/worker.py's tape-mismatch error, I1). */
export function tapeMismatchWarning(
  designWidthMm: number,
  connected: boolean,
  loadedWidthMm: number | null | undefined,
): string | null {
  if (!connected || loadedWidthMm == null || loadedWidthMm === designWidthMm) return null;
  return `Printer has ${loadedWidthMm}mm tape loaded — this label is designed for ${designWidthMm}mm`;
}
