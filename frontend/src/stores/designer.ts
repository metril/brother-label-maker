import { create } from "zustand";
import type { HAlign, LabelDefinition, Tape, TextLabelParams } from "../api/types";

// TZe tape widths and font families used to be hardcoded here (kept in
// lockstep by hand with backend/driver/geometry.py's _TZE_ROWS and
// backend/render/fonts.py's bundled set -- two drift risks). B2 replaced
// both with live data: TapeSelector reads GET /api/tapes (via useTapes),
// TextLabelForm's font select reads GET /api/fonts (via useFonts).

export const MAX_LINES = 4;
export const MIN_LINES = 1;

interface DesignerState {
  tape: Tape;
  params: TextLabelParams;

  setTapeWidthMm: (widthMm: number) => void;
  setLine: (index: number, text: string) => void;
  addLine: () => void;
  removeLine: (index: number) => void;
  setFontFamily: (family: string) => void;
  setBold: (bold: boolean) => void;
  setFontSizeMode: (mode: "auto" | "manual") => void;
  setFontSizePx: (px: number) => void;
  setHAlign: (align: HAlign) => void;
  setLengthMode: (mode: "auto" | "manual") => void;
  setLengthMm: (mm: number) => void;
  setPaddingMm: (mm: number) => void;
}

const initialParams: TextLabelParams = {
  lines: [""],
  font_family: "Inter",
  bold: false,
  font_size_px: null,
  h_align: "center",
  length_mm: null,
  padding_mm: 2.0,
};

export const useDesignerStore = create<DesignerState>((set) => ({
  tape: { width_mm: 24, family: "tze" },
  params: initialParams,

  setTapeWidthMm: (widthMm) =>
    set((state) => ({ tape: { ...state.tape, width_mm: widthMm } })),

  setLine: (index, text) =>
    set((state) => {
      const lines = [...state.params.lines];
      lines[index] = text;
      return { params: { ...state.params, lines } };
    }),

  addLine: () =>
    set((state) => {
      if (state.params.lines.length >= MAX_LINES) return state;
      return { params: { ...state.params, lines: [...state.params.lines, ""] } };
    }),

  removeLine: (index) =>
    set((state) => {
      if (state.params.lines.length <= MIN_LINES) return state;
      const lines = state.params.lines.filter((_, i) => i !== index);
      return { params: { ...state.params, lines } };
    }),

  setFontFamily: (family) => set((state) => ({ params: { ...state.params, font_family: family } })),

  setBold: (bold) => set((state) => ({ params: { ...state.params, bold } })),

  setFontSizeMode: (mode) =>
    set((state) => ({
      params: { ...state.params, font_size_px: mode === "auto" ? null : (state.params.font_size_px ?? 24) },
    })),

  setFontSizePx: (px) => set((state) => ({ params: { ...state.params, font_size_px: px } })),

  setHAlign: (align) => set((state) => ({ params: { ...state.params, h_align: align } })),

  setLengthMode: (mode) =>
    set((state) => ({
      params: { ...state.params, length_mm: mode === "auto" ? null : (state.params.length_mm ?? 40) },
    })),

  setLengthMm: (mm) => set((state) => ({ params: { ...state.params, length_mm: mm } })),

  setPaddingMm: (mm) => set((state) => ({ params: { ...state.params, padding_mm: mm } })),
}));

/** True when the form has at least one non-whitespace line -- the backend
 * (TextLabelParams._check_lines) 422s on an all-blank `lines` list, so the
 * UI gates preview/print requests on this instead of round-tripping a 422
 * for the empty-textarea case every user hits on first load. */
export function hasRenderableContent(params: TextLabelParams): boolean {
  return params.lines.some((line) => line.trim() !== "");
}

export function buildDefinition(tape: Tape, params: TextLabelParams): LabelDefinition {
  return { type: "text", tape, params };
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
