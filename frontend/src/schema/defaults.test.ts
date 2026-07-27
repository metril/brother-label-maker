import { describe, expect, it } from "vitest";
import { buildDefaultParams, buildItemDefault } from "./defaults";
import type { JsonSchemaObject } from "./jsonSchema";

describe("buildDefaultParams", () => {
  it("trusts an explicit schema `default` verbatim, and falls back to null for a nullable field with none", () => {
    const schema: JsonSchemaObject = {
      type: "object",
      properties: {
        font_family: { type: "string", default: "Inter" },
        bold: { type: "boolean", default: false },
        padding_mm: { type: "number", default: 2.0 },
        font_size_px: { anyOf: [{ type: "integer" }, { type: "null" }], default: null },
      },
    };
    expect(buildDefaultParams(schema)).toEqual({
      font_family: "Inter",
      bold: false,
      padding_mm: 2.0,
      font_size_px: null,
    });
  });

  it("seeds an array field with exactly `minItems` item-default rows when the schema has no top-level default (patch_panel.blocks' own shape)", () => {
    const root: JsonSchemaObject = {
      type: "object",
      $defs: {
        BlockText: { type: "object", properties: { lines: { type: "array", items: { type: "string" } } } },
      },
      properties: {
        blocks: { type: "array", items: { $ref: "#/$defs/BlockText" }, minItems: 1, maxItems: 50 },
      },
      required: ["blocks"],
    };
    expect(buildDefaultParams(root)).toEqual({ blocks: [{ lines: [] }] });
  });

  it("picks a sensible default (1, not the bound minimum) for a bounded number item schema with no default -- e.g. a fresh width_multiplier", () => {
    const itemSchema: JsonSchemaObject = { type: "number", minimum: 0.1, maximum: 9.5 };
    const root: JsonSchemaObject = { type: "object", properties: {} };
    expect(buildItemDefault(itemSchema, root)).toBe(1);
  });
});
