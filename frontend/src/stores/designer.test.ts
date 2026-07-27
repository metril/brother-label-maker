import { describe, expect, it } from "vitest";
import { hasRenderableContent, tapeMismatchWarning } from "./designer";
import type { TextLabelParams } from "../api/types";

function params(lines: string[]): TextLabelParams {
  return {
    lines,
    font_family: "Inter",
    bold: false,
    font_size_px: null,
    h_align: "center",
    length_mm: null,
    padding_mm: 2,
  };
}

describe("hasRenderableContent", () => {
  it("is false for an all-blank lines list", () => {
    expect(hasRenderableContent(params(["", "   "]))).toBe(false);
  });

  it("is true once at least one line has non-whitespace content", () => {
    expect(hasRenderableContent(params(["", "hi"]))).toBe(true);
  });
});

// I1: tapeMismatchWarning is the pure logic behind Designer's amber banner
// -- exercised directly here (deterministic, no async/query timing) so
// "absent on match/disconnected" is pinned exhaustively; Designer.test.tsx
// covers the "appears on mismatch" case end to end through the real hook
// wiring.
describe("tapeMismatchWarning", () => {
  it("returns null when disconnected, regardless of the reported width", () => {
    expect(tapeMismatchWarning(24, false, 12)).toBeNull();
  });

  it("returns null when the loaded width is not yet known", () => {
    expect(tapeMismatchWarning(24, true, null)).toBeNull();
    expect(tapeMismatchWarning(24, true, undefined)).toBeNull();
  });

  it("returns null when the loaded width matches the design", () => {
    expect(tapeMismatchWarning(24, true, 24)).toBeNull();
  });

  it("returns a human-readable message when the loaded width differs from the design", () => {
    expect(tapeMismatchWarning(24, true, 12)).toBe(
      "Printer has 12mm tape loaded — this label is designed for 24mm",
    );
  });
});
