import { describe, expect, it, beforeEach } from "vitest";
import { tapeMismatchWarning, useDesignerStore } from "./designer";
import type { JsonSchemaObject } from "../schema/jsonSchema";

const TEXT_SCHEMA: JsonSchemaObject = {
  type: "object",
  properties: {
    lines: { type: "array", items: { type: "string" }, minItems: 1, maxItems: 4 },
    font_family: { type: "string", default: "Inter" },
  },
  required: ["lines"],
};

const INITIAL_STATE = useDesignerStore.getState();

beforeEach(() => {
  useDesignerStore.setState(INITIAL_STATE, true);
});

describe("useDesignerStore", () => {
  it("selectType seeds a type's params from its schema's own defaults the first time it's visited", () => {
    useDesignerStore.getState().selectType("text", TEXT_SCHEMA);

    const state = useDesignerStore.getState();
    expect(state.selectedType).toBe("text");
    expect(state.paramsByType.text).toEqual({ lines: [""], font_family: "Inter" });
  });

  it("re-selecting a type already visited this session keeps its edited params (doesn't reset to defaults)", () => {
    useDesignerStore.getState().selectType("text", TEXT_SCHEMA);
    useDesignerStore.getState().setParams("text", { lines: ["HELLO"], font_family: "Inter" });

    useDesignerStore.getState().selectType("barcode", { type: "object", properties: {} });
    useDesignerStore.getState().selectType("text", TEXT_SCHEMA);

    expect(useDesignerStore.getState().paramsByType.text).toEqual({ lines: ["HELLO"], font_family: "Inter" });
  });

  it("setTapeWidthMm/setTapeFamily update only the field named", () => {
    useDesignerStore.getState().setTapeFamily("hse_2_1");
    useDesignerStore.getState().setTapeWidthMm(8.8);

    expect(useDesignerStore.getState().tape).toEqual({ width_mm: 8.8, family: "hse_2_1" });
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
