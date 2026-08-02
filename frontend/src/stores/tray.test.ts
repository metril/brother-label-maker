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

/** The tray is persisted (zustand's `persist` middleware, key "lm-tray-v1")
 * so it survives a reload -- the whole point of accumulating several
 * designs before printing them together, which a refresh used to silently
 * wipe. `png` is deliberately nulled on write (a captured preview is
 * refetchable on demand, see hooks/useTrayPreviews.ts; there's no reason to
 * grow localStorage with base64 image data). */
describe("useTrayStore persistence (zustand persist middleware)", () => {
  it("partialize nulls out every item's own png before writing to localStorage", () => {
    useTrayStore.getState().addItem({ definition: def("A"), png: "data:image/png;base64,AAAA", lengthMm: 10, label: "A" });

    const raw = localStorage.getItem("lm-tray-v1");
    expect(raw).not.toBeNull();
    const persisted = JSON.parse(raw!) as { state: { items: { png: string | null; label: string }[] } };
    expect(persisted.state.items).toHaveLength(1);
    expect(persisted.state.items[0]!.png).toBeNull();
    expect(persisted.state.items[0]!.label).toBe("A");
  });

  it("persists chainMode/autoCut alongside the item list", () => {
    useTrayStore.getState().setChainMode("chain_ff");
    useTrayStore.getState().setAutoCut(false);

    const persisted = JSON.parse(localStorage.getItem("lm-tray-v1")!) as {
      state: { chainMode: string; autoCut: boolean };
    };
    expect(persisted.state.chainMode).toBe("chain_ff");
    expect(persisted.state.autoCut).toBe(false);
  });

  it("rehydrates items/chainMode/autoCut from a previously persisted snapshot (version 1's own migrate passthrough)", async () => {
    const restoredItem = { id: "restored-1", definition: def("RESTORED"), png: null, lengthMm: 12, label: "Text — RESTORED" };
    localStorage.setItem(
      "lm-tray-v1",
      JSON.stringify({
        state: { items: [restoredItem], chainMode: "strip_marks", autoCut: false },
        version: 1,
      }),
    );

    await useTrayStore.persist.rehydrate();

    const state = useTrayStore.getState();
    expect(state.items).toEqual([restoredItem]);
    expect(state.chainMode).toBe("strip_marks");
    expect(state.autoCut).toBe(false);
  });
});
