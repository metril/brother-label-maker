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

  it("setSelectedIndex updates `selectedIndex` only, defaulting to 0", () => {
    expect(usePrintPreviewStore.getState().selectedIndex).toBe(0);

    usePrintPreviewStore.getState().setSelectedIndex(2);
    expect(usePrintPreviewStore.getState().selectedIndex).toBe(2);
    expect(usePrintPreviewStore.getState().open).toBe(false);

    usePrintPreviewStore.getState().setSelectedIndex(0);
    expect(usePrintPreviewStore.getState().selectedIndex).toBe(0);
  });
});

/** `open` alone is persisted (zustand's `persist` middleware, key
 * "lm-chain-preview-v1") -- see the store's own docstring for why: it's a
 * standing preference for whether the bottom preview deck is shown or
 * hidden, unlike `selectedIndex`, which stays purely in-memory/session-only
 * the same way it always has. */
describe("usePrintPreviewStore persistence (zustand persist middleware)", () => {
  it("partialize writes `open` (and only `open`) to localStorage", () => {
    usePrintPreviewStore.getState().openDrawer();

    const raw = localStorage.getItem("lm-chain-preview-v1");
    expect(raw).not.toBeNull();
    const persisted = JSON.parse(raw!) as { state: Record<string, unknown> };
    expect(persisted.state).toEqual({ open: true });
  });

  it("rehydrates `open` from a previously persisted snapshot", async () => {
    localStorage.setItem(
      "lm-chain-preview-v1",
      JSON.stringify({ state: { open: true }, version: 2 }),
    );

    await usePrintPreviewStore.persist.rehydrate();

    const state = usePrintPreviewStore.getState();
    expect(state.open).toBe(true);
  });

  // Part 2 (cycling through queued labels): `selectedIndex` is session-only
  // -- which label within the CURRENT job someone's looking at has no
  // business surviving a reload.
  it("`selectedIndex` never reaches localStorage, even set to a nonzero value", () => {
    usePrintPreviewStore.getState().setSelectedIndex(2);
    usePrintPreviewStore.getState().openDrawer();

    const raw = localStorage.getItem("lm-chain-preview-v1");
    const persisted = JSON.parse(raw!) as { state: Record<string, unknown> };
    expect(persisted.state).toEqual({ open: true });
    expect(persisted.state).not.toHaveProperty("selectedIndex");
  });
});

describe("v1 -> v2 migration", () => {
  it("migrates a persisted `docked: true` snapshot to `open: true`", async () => {
    localStorage.setItem(
      "lm-chain-preview-v1",
      JSON.stringify({ state: { docked: true }, version: 1 }),
    );

    await usePrintPreviewStore.persist.rehydrate();

    expect(usePrintPreviewStore.getState().open).toBe(true);
  });

  it("migrates a persisted `docked: false` snapshot to `open: false`", async () => {
    localStorage.setItem(
      "lm-chain-preview-v1",
      JSON.stringify({ state: { docked: false }, version: 1 }),
    );

    await usePrintPreviewStore.persist.rehydrate();

    expect(usePrintPreviewStore.getState().open).toBe(false);
  });

  it("migrates a persisted snapshot with no `docked` field to `open: false`, without throwing", async () => {
    localStorage.setItem(
      "lm-chain-preview-v1",
      JSON.stringify({ state: {}, version: 1 }),
    );

    await expect(usePrintPreviewStore.persist.rehydrate()).resolves.not.toThrow();

    expect(usePrintPreviewStore.getState().open).toBe(false);
  });
});
