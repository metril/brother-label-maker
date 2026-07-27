import { describe, expect, it } from "vitest";
import { hasNumberOutOfRange, isNumberFieldInvalid, numberFieldErrorMessage } from "./numberValidity";
import type { JsonSchemaObject } from "./jsonSchema";

const BOUNDED = { minimum: 5, maximum: 300 };

describe("isNumberFieldInvalid / numberFieldErrorMessage", () => {
  it("flags a missing/empty value as invalid with 'enter a value', distinct from an out-of-range one", () => {
    expect(isNumberFieldInvalid(undefined, BOUNDED)).toBe(true);
    expect(numberFieldErrorMessage(undefined, BOUNDED)).toBe("enter a value");
    expect(numberFieldErrorMessage(Number.NaN, BOUNDED)).toBe("enter a value");

    expect(isNumberFieldInvalid(400, BOUNDED)).toBe(true);
    expect(numberFieldErrorMessage(400, BOUNDED)).toBe("must be between 5 and 300");
  });

  it("is valid for any in-range number, with no message", () => {
    expect(isNumberFieldInvalid(15, BOUNDED)).toBe(false);
    expect(numberFieldErrorMessage(15, BOUNDED)).toBeNull();
  });

  it("handles a one-sided bound (min only, or max only)", () => {
    expect(numberFieldErrorMessage(2, { minimum: 5 })).toBe("must be at least 5");
    expect(numberFieldErrorMessage(500, { maximum: 300 })).toBe("must be at most 300");
  });
});

describe("hasNumberOutOfRange", () => {
  const schema: JsonSchemaObject = {
    type: "object",
    properties: {
      padding_mm: { type: "number", minimum: 0 },
      font_size_px: { anyOf: [{ type: "integer", minimum: 6, maximum: 128 }, { type: "null" }], default: null },
    },
  };

  it("is false when every number field is present and in range (nullable fields left Auto/null don't count)", () => {
    expect(hasNumberOutOfRange(schema, { padding_mm: 2, font_size_px: null })).toBe(false);
  });

  it("is true when a top-level number field is out of range or cleared", () => {
    expect(hasNumberOutOfRange(schema, { padding_mm: -1, font_size_px: null })).toBe(true);
    expect(hasNumberOutOfRange(schema, { padding_mm: undefined, font_size_px: null })).toBe(true);
  });

  it("is true when a Manual (non-null) nullable number field is out of its own bounds", () => {
    expect(hasNumberOutOfRange(schema, { padding_mm: 2, font_size_px: 500 })).toBe(true);
  });

  it("recurses into array-of-object rows (patch_panel's blocks / breaker_box's breakers shape)", () => {
    const root: JsonSchemaObject = {
      type: "object",
      $defs: { BreakerSpec: { type: "object", properties: { poles: { type: "integer", minimum: 1, maximum: 4 } } } },
      properties: { breakers: { type: "array", items: { $ref: "#/$defs/BreakerSpec" } } },
    };
    expect(hasNumberOutOfRange(root, { breakers: [{ poles: 2 }, { poles: 1 }] })).toBe(false);
    expect(hasNumberOutOfRange(root, { breakers: [{ poles: 2 }, { poles: 9 }] })).toBe(true);
  });

  it("recurses into array-of-number items (patch_panel's multipliers shape)", () => {
    const root: JsonSchemaObject = {
      type: "object",
      properties: {
        multipliers: {
          anyOf: [{ type: "array", items: { type: "number", minimum: 0.1, maximum: 9.5 } }, { type: "null" }],
          default: null,
        },
      },
    };
    expect(hasNumberOutOfRange(root, { multipliers: null })).toBe(false);
    expect(hasNumberOutOfRange(root, { multipliers: [1, 2] })).toBe(false);
    expect(hasNumberOutOfRange(root, { multipliers: [1, 20] })).toBe(true);
  });
});
