import { beforeEach, describe, expect, it } from "vitest";
import { useTrayStore } from "./tray";
import type { LabelDefinition } from "../api/types";

const INITIAL_STATE = useTrayStore.getState();

beforeEach(() => {
  useTrayStore.setState(INITIAL_STATE, true);
});

function def(text: string): LabelDefinition {
  return { type: "text", tape: { width_mm: 24, family: "tze" }, params: { lines: [text] } };
}

describe("useTrayStore", () => {
  it("addItem appends a new item with its own generated id", () => {
    useTrayStore.getState().addItem({ definition: def("A"), png: null, lengthMm: 10, label: "Text — A" });
    useTrayStore.getState().addItem({ definition: def("B"), png: null, lengthMm: 12, label: "Text — B" });

    const items = useTrayStore.getState().items;
    expect(items).toHaveLength(2);
    expect(items[0]!.label).toBe("Text — A");
    expect(items[1]!.label).toBe("Text — B");
    expect(items[0]!.id).not.toBe(items[1]!.id);
  });

  it("removeItem removes only the targeted item", () => {
    useTrayStore.getState().addItem({ definition: def("A"), png: null, lengthMm: 10, label: "A" });
    useTrayStore.getState().addItem({ definition: def("B"), png: null, lengthMm: 10, label: "B" });
    const [first, second] = useTrayStore.getState().items;

    useTrayStore.getState().removeItem(first!.id);

    expect(useTrayStore.getState().items).toEqual([second]);
  });

  it("moveUp/moveDown swap adjacent items and clamp at the boundaries", () => {
    useTrayStore.getState().addItem({ definition: def("A"), png: null, lengthMm: 10, label: "A" });
    useTrayStore.getState().addItem({ definition: def("B"), png: null, lengthMm: 10, label: "B" });
    useTrayStore.getState().addItem({ definition: def("C"), png: null, lengthMm: 10, label: "C" });
    const [a, , c] = useTrayStore.getState().items;

    // Clamped: the first item can't move further up.
    useTrayStore.getState().moveUp(a!.id);
    expect(useTrayStore.getState().items.map((i) => i.label)).toEqual(["A", "B", "C"]);

    useTrayStore.getState().moveDown(a!.id);
    expect(useTrayStore.getState().items.map((i) => i.label)).toEqual(["B", "A", "C"]);

    // Clamped: the last item can't move further down.
    useTrayStore.getState().moveDown(c!.id);
    expect(useTrayStore.getState().items.map((i) => i.label)).toEqual(["B", "A", "C"]);
  });

  it("duplicateItem inserts a copy (own id, same content) directly after the original", () => {
    useTrayStore.getState().addItem({ definition: def("A"), png: null, lengthMm: 10, label: "A" });
    useTrayStore.getState().addItem({ definition: def("B"), png: null, lengthMm: 10, label: "B" });
    const [a] = useTrayStore.getState().items;

    useTrayStore.getState().duplicateItem(a!.id);

    const items = useTrayStore.getState().items;
    expect(items.map((i) => i.label)).toEqual(["A", "A", "B"]);
    expect(items[0]!.id).not.toBe(items[1]!.id);
    expect(items[1]!.definition).toEqual(items[0]!.definition);
  });

  it("clear empties the tray without touching chainMode/autoCut", () => {
    useTrayStore.getState().addItem({ definition: def("A"), png: null, lengthMm: 10, label: "A" });
    useTrayStore.getState().setChainMode("chain_ff");

    useTrayStore.getState().clear();

    expect(useTrayStore.getState().items).toEqual([]);
    expect(useTrayStore.getState().chainMode).toBe("chain_ff");
  });

  it("setChainMode/setAutoCut update only the field named", () => {
    useTrayStore.getState().setChainMode("strip_marks");
    useTrayStore.getState().setAutoCut(false);

    expect(useTrayStore.getState().chainMode).toBe("strip_marks");
    expect(useTrayStore.getState().autoCut).toBe(false);
  });
});
