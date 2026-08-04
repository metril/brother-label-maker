import { afterEach, describe, expect, it } from "vitest";
import { usePrintPreviewStore } from "./printPreview";

const INITIAL_STATE = usePrintPreviewStore.getState();

afterEach(() => {
  usePrintPreviewStore.setState(INITIAL_STATE, true);
});

describe("usePrintPreviewStore", () => {
  it("openDrawer/closeDrawer/toggle flip `open` only", () => {
    expect(usePrintPreviewStore.getState().open).toBe(false);

    usePrintPreviewStore.getState().openDrawer();
    expect(usePrintPreviewStore.getState().open).toBe(true);

    usePrintPreviewStore.getState().closeDrawer();
    expect(usePrintPreviewStore.getState().open).toBe(false);

    usePrintPreviewStore.getState().toggle();
    expect(usePrintPreviewStore.getState().open).toBe(true);
    usePrintPreviewStore.getState().toggle();
    expect(usePrintPreviewStore.getState().open).toBe(false);
  });

  it("toggleDocked flips `docked` only, defaulting to false", () => {
    expect(usePrintPreviewStore.getState().docked).toBe(false);

    usePrintPreviewStore.getState().toggleDocked();
    expect(usePrintPreviewStore.getState().docked).toBe(true);
    expect(usePrintPreviewStore.getState().open).toBe(false);

    usePrintPreviewStore.getState().toggleDocked();
    expect(usePrintPreviewStore.getState().docked).toBe(false);
  });

  it("setSelectedIndex updates `selectedIndex` only, defaulting to 0", () => {
    expect(usePrintPreviewStore.getState().selectedIndex).toBe(0);

    usePrintPreviewStore.getState().setSelectedIndex(2);
    expect(usePrintPreviewStore.getState().selectedIndex).toBe(2);
    expect(usePrintPreviewStore.getState().open).toBe(false);
    expect(usePrintPreviewStore.getState().docked).toBe(false);

    usePrintPreviewStore.getState().setSelectedIndex(0);
    expect(usePrintPreviewStore.getState().selectedIndex).toBe(0);
  });
});

/** `docked` alone is persisted (zustand's `persist` middleware, key
 * "lm-chain-preview-v1") -- see the store's own docstring for why: it's a
 * standing layout preference, unlike `open`, which stays purely
 * in-memory/session-only the same way it always has. */
describe("usePrintPreviewStore persistence (zustand persist middleware)", () => {
  it("partialize writes `docked` (and only `docked`) to localStorage", () => {
    usePrintPreviewStore.getState().toggleDocked();

    const raw = localStorage.getItem("lm-chain-preview-v1");
    expect(raw).not.toBeNull();
    const persisted = JSON.parse(raw!) as { state: Record<string, unknown> };
    expect(persisted.state).toEqual({ docked: true });
  });

  it("`open` never reaches localStorage, even while true", () => {
    usePrintPreviewStore.getState().openDrawer();
    usePrintPreviewStore.getState().toggleDocked();

    const raw = localStorage.getItem("lm-chain-preview-v1");
    const persisted = JSON.parse(raw!) as { state: Record<string, unknown> };
    expect(persisted.state).not.toHaveProperty("open");
  });

  it("rehydrates `docked` from a previously persisted snapshot, leaving `open` at its own default", async () => {
    localStorage.setItem(
      "lm-chain-preview-v1",
      JSON.stringify({ state: { docked: true }, version: 1 }),
    );

    await usePrintPreviewStore.persist.rehydrate();

    const state = usePrintPreviewStore.getState();
    expect(state.docked).toBe(true);
    expect(state.open).toBe(false);
  });

  // Part 2 (cycling through queued labels): `selectedIndex` is session-only,
  // same category as `open` -- which label within the CURRENT job someone's
  // looking at has no business surviving a reload.
  it("`selectedIndex` never reaches localStorage, even set to a nonzero value", () => {
    usePrintPreviewStore.getState().setSelectedIndex(2);
    usePrintPreviewStore.getState().toggleDocked();

    const raw = localStorage.getItem("lm-chain-preview-v1");
    const persisted = JSON.parse(raw!) as { state: Record<string, unknown> };
    expect(persisted.state).toEqual({ docked: true });
    expect(persisted.state).not.toHaveProperty("selectedIndex");
  });
});
