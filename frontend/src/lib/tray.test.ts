import { describe, expect, it } from "vitest";
import { describeCurrentDesign, nextTrayItemId } from "./tray";
import type { JsonSchemaObject } from "../schema/jsonSchema";

const TEXT_SCHEMA: JsonSchemaObject = {
  type: "object",
  properties: { lines: { type: "array", items: { type: "string" } } },
};

describe("describeCurrentDesign", () => {
  it("combines the type title with the first non-blank text content", () => {
    expect(describeCurrentDesign("Text", TEXT_SCHEMA, { lines: ["UPLINK-A"] })).toBe("Text — UPLINK-A");
  });

  it("falls back to just the type title when there's no qualifying text yet", () => {
    expect(describeCurrentDesign("Patch Panel", TEXT_SCHEMA, { lines: [""] })).toBe("Patch Panel");
    expect(describeCurrentDesign("Patch Panel", TEXT_SCHEMA, {})).toBe("Patch Panel");
  });

  it("truncates long text with an ellipsis rather than overflowing the caption", () => {
    const longText = "A".repeat(60);
    const result = describeCurrentDesign("Text", TEXT_SCHEMA, { lines: [longText] });
    expect(result.length).toBeLessThan(longText.length + "Text — ".length);
    expect(result.endsWith("…")).toBe(true);
  });
});

describe("nextTrayItemId", () => {
  it("generates distinct ids on successive calls", () => {
    const a = nextTrayItemId();
    const b = nextTrayItemId();
    expect(a).not.toBe(b);
    expect(a.length).toBeGreaterThan(0);
  });
});
