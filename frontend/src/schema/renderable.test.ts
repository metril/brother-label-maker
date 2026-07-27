import { describe, expect, it } from "vitest";
import { hasRenderableContent } from "./renderable";
import type { JsonSchemaObject } from "./jsonSchema";

const TEXT_LIKE_SCHEMA: JsonSchemaObject = {
  type: "object",
  properties: { lines: { type: "array", items: { type: "string" }, minItems: 1, maxItems: 4 } },
  required: ["lines"],
};

const BARCODE_LIKE_SCHEMA: JsonSchemaObject = {
  type: "object",
  properties: { data: { type: "string", minLength: 1 } },
  required: ["data"],
};

const PATCH_PANEL_LIKE_SCHEMA: JsonSchemaObject = {
  type: "object",
  $defs: { BlockText: { type: "object", properties: { lines: { type: "array", items: { type: "string" } } } } },
  properties: { blocks: { type: "array", items: { $ref: "#/$defs/BlockText" }, minItems: 1 } },
  required: ["blocks"],
};

const PUNCH_DOWN_LIKE_SCHEMA: JsonSchemaObject = {
  type: "object",
  properties: { n_blocks: { type: "integer", default: 6 } },
  // no `required` at all -- every field has a schema default.
};

describe("hasRenderableContent", () => {
  it("gates a required array-of-string field on at least one non-blank entry (text/cable_wrap/cable_flag's own `lines` rule), and a required string field on being non-blank (barcode's `data`)", () => {
    expect(hasRenderableContent(TEXT_LIKE_SCHEMA, { lines: ["", "   "] })).toBe(false);
    expect(hasRenderableContent(TEXT_LIKE_SCHEMA, { lines: ["", "hi"] })).toBe(true);

    expect(hasRenderableContent(BARCODE_LIKE_SCHEMA, { data: "" })).toBe(false);
    expect(hasRenderableContent(BARCODE_LIKE_SCHEMA, { data: "12345" })).toBe(true);
  });

  it("a required array-of-object field only needs to be non-empty (a blank block is still a valid, renderable block) -- and a schema with no `required` at all is always renderable", () => {
    expect(hasRenderableContent(PATCH_PANEL_LIKE_SCHEMA, { blocks: [] })).toBe(false);
    expect(hasRenderableContent(PATCH_PANEL_LIKE_SCHEMA, { blocks: [{ lines: [] }] })).toBe(true);

    expect(hasRenderableContent(PUNCH_DOWN_LIKE_SCHEMA, { n_blocks: 6 })).toBe(true);
  });
});
