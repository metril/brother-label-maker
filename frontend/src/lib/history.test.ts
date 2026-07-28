import { describe, expect, it } from "vitest";
import { extractSingleLabel } from "./history";

const LABEL = { type: "text", tape: { width_mm: 24, family: "tze" }, params: { lines: ["A"] } };

describe("extractSingleLabel", () => {
  it("returns the single label for a one-label, non-serialized print request", () => {
    expect(extractSingleLabel({ labels: [LABEL], options: {} })).toEqual(LABEL);
  });

  it("returns null when serialization was set (a run, not a single label)", () => {
    expect(extractSingleLabel({ labels: [LABEL], serialization: { kind: "numeric" } })).toBeNull();
  });

  it("returns null for a multi-label (tray) print request", () => {
    expect(extractSingleLabel({ labels: [LABEL, LABEL] })).toBeNull();
  });

  it("returns null for zero labels", () => {
    expect(extractSingleLabel({ labels: [] })).toBeNull();
  });

  it("returns null for a malformed/unrecognized shape", () => {
    expect(extractSingleLabel(null)).toBeNull();
    expect(extractSingleLabel({})).toBeNull();
    expect(extractSingleLabel({ labels: [{ type: "text" }] })).toBeNull();
    expect(extractSingleLabel("not an object")).toBeNull();
  });
});
