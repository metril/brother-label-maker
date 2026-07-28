import { create } from "zustand";
import type { LabelDefinition, Sequence, Tape, TapeFamily } from "../api/types";
import { DEFAULT_SEQUENCE } from "../lib/sequence";
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
  /** task 2.11: off by default -- a single toggle in the Serialize panel
   * (components/SequenceEditor.tsx) turns a plain single-label print into
   * a serialized run. Store-level (not component-local state) because it
   * gates behavior across several siblings at once: the feed deck's
   * preview-index stepper, the Job Tray/Print button's request body and
   * "Print N labels" label, and the small per-field token-insert
   * affordances SchemaField/ArrayOfStrings render next to text inputs. */
  serializationEnabled: boolean;
  /** The current (possibly still-invalid-while-editing) Sequence spec --
   * see lib/sequence.ts's validateSequence for the client-side bounds
   * checks, and hooks/useSequenceExpand.ts for the debounced POST
   * /api/render/expand call that confirms it's actually printable. */
  sequence: Sequence;

  setTapeWidthMm: (widthMm: number) => void;
  setTapeFamily: (family: TapeFamily) => void;
  /** Makes `type` the active type, seeding its params from `schema`'s own
   * defaults (schema/defaults.ts) the FIRST time it's selected -- a later
   * re-selection (switching back to a type visited earlier this session)
   * keeps whatever was already there. */
  selectType: (type: string, schema: JsonSchemaObject) => void;
  setParams: (type: string, params: Record<string, unknown>) => void;
  setSerializationEnabled: (enabled: boolean) => void;
  setSequence: (sequence: Sequence) => void;
}

export const useDesignerStore = create<DesignerState>((set) => ({
  tape: { width_mm: 24, family: "tze" },
  selectedType: null,
  paramsByType: {},
  serializationEnabled: false,
  sequence: DEFAULT_SEQUENCE,

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

  setSerializationEnabled: (enabled) => set({ serializationEnabled: enabled }),

  setSequence: (sequence) => set({ sequence }),
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
