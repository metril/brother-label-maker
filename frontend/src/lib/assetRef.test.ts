import { describe, expect, it } from "vitest";
import { normalizeAssetId, parseScan } from "./assetRef";

const UUID = "3f2a9c1e-5b7d-4e0a-9c11-2d8f6a0b1c77";

describe("parseScan", () => {
  it("parses asset URLs on any host", () => {
    expect(parseScan("https://box.example.com/a/000-123")).toEqual({ kind: "asset", value: "000-123" });
    expect(parseScan("http://192.168.1.5:3100/a/000-123?x=1", "https://other.host")).toEqual({
      kind: "asset",
      value: "000-123",
    });
  });
  it("parses item and location URLs, including a sub-path base", () => {
    expect(parseScan(`https://h/item/${UUID}`)).toEqual({ kind: "entity", value: UUID });
    expect(parseScan(`https://h/location/${UUID}`)).toEqual({ kind: "location", value: UUID });
    expect(parseScan("https://h/homebox/a/000-007", "https://h/homebox/")).toEqual({
      kind: "asset",
      value: "000-007",
    });
  });
  it("accepts bare asset ids and numbers", () => {
    expect(parseScan("#000-001")).toEqual({ kind: "asset", value: "000-001" });
    expect(parseScan(" 1234 ")).toEqual({ kind: "asset", value: "001-234" });
  });
  it("rejects non-HomeBox content", () => {
    expect(parseScan("")).toBeNull();
    expect(parseScan("https://example.com/")).toBeNull();
    expect(parseScan("https://example.com/a/not-an-id")).toBeNull();
    expect(parseScan("hello world")).toBeNull();
    expect(parseScan("0123456789012")).toBeNull();
  });
});

describe("normalizeAssetId", () => {
  it("pads bare numbers to HomeBox's 3-3 shape", () => {
    expect(normalizeAssetId("7")).toBe("000-007");
    expect(normalizeAssetId("000-007")).toBe("000-007");
    expect(normalizeAssetId("x")).toBeNull();
  });
});
