import { describe, expect, it } from "vitest";
import {
  collationPattern,
  csvColumns,
  DEFAULT_SEQUENCE,
  effectiveCount,
  firstTextFieldValue,
  parseListTextarea,
  sequenceTotalLabels,
  validateSequence,
} from "./sequence";
import type { JsonSchemaObject } from "../schema/jsonSchema";
import type { Sequence } from "../api/types";

function numeric(overrides: Partial<Sequence> = {}): Sequence {
  return { ...DEFAULT_SEQUENCE, kind: "numeric", ...overrides };
}

describe("validateSequence -- client-side bounds (task 2.11 brief's own test list)", () => {
  it("count 501 is out of bounds (max 500)", () => {
    expect(validateSequence(numeric({ count: 501 })).count).toMatch(/500/);
  });

  it("copies_per_value 101 is out of bounds (max 100)", () => {
    expect(validateSequence(numeric({ copies_per_value: 101 })).copiesPerValue).toMatch(/100/);
  });

  it("pad_width 7 is out of bounds (max 6)", () => {
    expect(validateSequence(numeric({ pad_width: 7 })).padWidth).toMatch(/6/);
  });

  it("step 0 is rejected", () => {
    expect(validateSequence(numeric({ step: 0 })).step).toMatch(/must not be 0/);
  });

  it('alpha_start "a1" fails the A-Z pattern', () => {
    const errors = validateSequence({ ...DEFAULT_SEQUENCE, kind: "alpha", alpha_start: "a1" });
    expect(errors.alphaStart).toBeTruthy();
  });

  it("a fully in-bounds numeric sequence has no errors", () => {
    expect(validateSequence(numeric({ count: 24, step: 1, pad_width: 2, copies_per_value: 1 }))).toEqual({});
  });

  it("list kind requires at least one non-blank value", () => {
    expect(validateSequence({ ...DEFAULT_SEQUENCE, kind: "list", values: [] }).values).toBeTruthy();
    expect(validateSequence({ ...DEFAULT_SEQUENCE, kind: "list", values: ["  ", ""] }).values).toBeTruthy();
    expect(validateSequence({ ...DEFAULT_SEQUENCE, kind: "list", values: ["A"] }).values).toBeUndefined();
  });

  it("csv kind requires at least one uploaded row", () => {
    expect(validateSequence({ ...DEFAULT_SEQUENCE, kind: "csv", rows: [] }).rows).toBeTruthy();
    expect(validateSequence({ ...DEFAULT_SEQUENCE, kind: "csv", rows: [{ port: "1" }] }).rows).toBeUndefined();
  });
});

describe("effectiveCount / sequenceTotalLabels", () => {
  it("numeric/alpha read `count`; list/csv derive from their own array length", () => {
    expect(effectiveCount(numeric({ count: 24 }))).toBe(24);
    expect(effectiveCount({ ...DEFAULT_SEQUENCE, kind: "list", values: ["A", "B", "C"] })).toBe(3);
    expect(effectiveCount({ ...DEFAULT_SEQUENCE, kind: "csv", rows: [{ a: "1" }, { a: "2" }] })).toBe(2);
  });

  it("total = effectiveCount * copies_per_value", () => {
    expect(sequenceTotalLabels(numeric({ count: 24, copies_per_value: 2 }))).toBe(48);
  });
});

describe("parseListTextarea", () => {
  it("splits on newlines, trims, and drops blank lines", () => {
    expect(parseListTextarea("A\n B \n\nC\n")).toEqual(["A", "B", "C"]);
  });

  it("an empty textarea parses to an empty list", () => {
    expect(parseListTextarea("")).toEqual([]);
    expect(parseListTextarea("   \n  \n")).toEqual([]);
  });
});

describe("csvColumns", () => {
  it("reads column names from the first row's own keys, in order", () => {
    expect(csvColumns([{ port: "1", label: "A" }, { port: "2", label: "B" }])).toEqual(["port", "label"]);
  });

  it("no rows -> no columns", () => {
    expect(csvColumns([])).toEqual([]);
  });
});

describe("firstTextFieldValue", () => {
  it("returns the first non-blank plain-string field's value, in schema order", () => {
    const schema: JsonSchemaObject = {
      type: "object",
      properties: {
        symbology: { type: "string", enum: ["qr", "code128"] },
        data: { type: "string" },
      },
    };
    expect(firstTextFieldValue(schema, { symbology: "qr", data: "PORT-{seq}" })).toBe("PORT-{seq}");
  });

  it("falls through a blank string field to the next candidate", () => {
    const schema: JsonSchemaObject = {
      type: "object",
      properties: {
        caption: { type: "string" },
        data: { type: "string" },
      },
    };
    expect(firstTextFieldValue(schema, { caption: "   ", data: "X" })).toBe("X");
  });

  it("reads an array-of-string field's first non-blank entry", () => {
    const schema: JsonSchemaObject = {
      type: "object",
      properties: { lines: { type: "array", items: { type: "string" } } },
    };
    expect(firstTextFieldValue(schema, { lines: ["", "PORT-{seq}", "second"] })).toBe("PORT-{seq}");
  });

  it("returns '' when nothing qualifies (e.g. no string-ish field has content yet)", () => {
    const schema: JsonSchemaObject = {
      type: "object",
      properties: { block_length_mm: { type: "number" } },
    };
    expect(firstTextFieldValue(schema, { block_length_mm: 40 })).toBe("");
  });
});

describe("collationPattern -- copies_adjacent vs sequence_repeated ordering", () => {
  it("3 values x 2 copies: copies_adjacent groups each value's copies together (A A B B C C)", () => {
    const { pattern, more } = collationPattern(["A", "B", "C"], 2, "copies_adjacent");
    expect(pattern).toEqual(["A", "A", "B", "B", "C", "C"]);
    expect(more).toBe(0);
  });

  it("3 values x 2 copies: sequence_repeated repeats the whole run (A B C A B C)", () => {
    const { pattern, more } = collationPattern(["A", "B", "C"], 2, "sequence_repeated");
    expect(pattern).toEqual(["A", "B", "C", "A", "B", "C"]);
    expect(more).toBe(0);
  });
});
