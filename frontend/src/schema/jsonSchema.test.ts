import { describe, expect, it } from "vitest";
import { classifyField, resolveRef, splitNullable, type JsonSchemaObject } from "./jsonSchema";

const ROOT: JsonSchemaObject = {
  type: "object",
  properties: {},
  $defs: {
    Separator: { type: "string", enum: ["tic", "dash", "line", "bold", "frame", "none"] },
    BlockText: { type: "object", properties: { lines: { type: "array", items: { type: "string" } } } },
  },
};

describe("resolveRef / splitNullable", () => {
  it("resolveRef follows a $ref into root.$defs; a non-$ref schema passes through unchanged", () => {
    expect(resolveRef({ $ref: "#/$defs/Separator" }, ROOT)).toBe(ROOT.$defs!.Separator);
    const plain: JsonSchemaObject = { type: "string" };
    expect(resolveRef(plain, ROOT)).toBe(plain);
  });

  it("splitNullable detects pydantic's `X | None = None` anyOf shape and resolves the non-null branch through $ref; a plain schema is reported non-nullable", () => {
    const nullable: JsonSchemaObject = {
      anyOf: [{ $ref: "#/$defs/Separator" }, { type: "null" }],
      default: null,
    };
    const result = splitNullable(nullable, ROOT);
    expect(result.nullable).toBe(true);
    expect(result.inner).toBe(ROOT.$defs!.Separator);

    const plain: JsonSchemaObject = { type: "string" };
    expect(splitNullable(plain, ROOT)).toEqual({ nullable: false, inner: plain });
  });
});

describe("classifyField", () => {
  it("classifies every field shape actually present across the 9 real label types", () => {
    expect(classifyField({ type: "string" })).toBe("string");
    expect(classifyField({ type: "integer" })).toBe("integer");
    expect(classifyField({ type: "number" })).toBe("number");
    expect(classifyField({ type: "boolean" })).toBe("boolean");
    expect(classifyField({ type: "string", enum: ["a", "b"] })).toBe("enum");
    expect(classifyField({ type: "array", items: { type: "string" } })).toBe("array-string");
    expect(classifyField({ type: "array", items: { type: "number" } })).toBe("array-number");
    expect(classifyField({ type: "array", items: { $ref: "#/$defs/BlockText" } })).toBe("array-object");
    expect(classifyField({ type: "array" })).toBe("unknown");
  });
});
