import { afterEach, describe, expect, it } from "vitest";
import { useTrayDrawerStore } from "./trayDrawer";

const INITIAL_STATE = useTrayDrawerStore.getState();

afterEach(() => {
  useTrayDrawerStore.setState(INITIAL_STATE, true);
});

describe("useTrayDrawerStore", () => {
  it("openDrawer/closeDrawer/toggle flip `open` only", () => {
    expect(useTrayDrawerStore.getState().open).toBe(false);

    useTrayDrawerStore.getState().openDrawer();
    expect(useTrayDrawerStore.getState().open).toBe(true);

    useTrayDrawerStore.getState().closeDrawer();
    expect(useTrayDrawerStore.getState().open).toBe(false);

    useTrayDrawerStore.getState().toggle();
    expect(useTrayDrawerStore.getState().open).toBe(true);
    useTrayDrawerStore.getState().toggle();
    expect(useTrayDrawerStore.getState().open).toBe(false);
  });
});

/** `open` alone is persisted (zustand's `persist` middleware, key
 * "lm-tray-drawer-v1") -- see the store's own docstring for why: at desktop
 * widths the tray is a real in-flow column, so "is it shown" is a standing
 * workspace preference now, unlike before this refactor when `open` stayed
 * purely in-memory/session-only. */
describe("useTrayDrawerStore persistence (zustand persist middleware)", () => {
  it("partialize writes `open` (and only `open`) to localStorage", () => {
    useTrayDrawerStore.getState().openDrawer();

    const raw = localStorage.getItem("lm-tray-drawer-v1");
    expect(raw).not.toBeNull();
    const persisted = JSON.parse(raw!) as { state: Record<string, unknown> };
    expect(persisted.state).toEqual({ open: true });
  });

  it("rehydrates `open` from a previously persisted snapshot", async () => {
    localStorage.setItem(
      "lm-tray-drawer-v1",
      JSON.stringify({ state: { open: true }, version: 2 }),
    );

    await useTrayDrawerStore.persist.rehydrate();

    const state = useTrayDrawerStore.getState();
    expect(state.open).toBe(true);
  });
});

describe("v1 -> v2 migration", () => {
  it("a previously-docked (v1) tray rehydrates as open", async () => {
    localStorage.setItem(
      "lm-tray-drawer-v1",
      JSON.stringify({ state: { docked: true }, version: 1 }),
    );

    await useTrayDrawerStore.persist.rehydrate();

    expect(useTrayDrawerStore.getState().open).toBe(true);
  });

  it("a previously-undocked (v1) tray rehydrates as closed", async () => {
    localStorage.setItem(
      "lm-tray-drawer-v1",
      JSON.stringify({ state: { docked: false }, version: 1 }),
    );

    await useTrayDrawerStore.persist.rehydrate();

    expect(useTrayDrawerStore.getState().open).toBe(false);
  });

  it("an empty v1 snapshot rehydrates as closed, without throwing", async () => {
    localStorage.setItem("lm-tray-drawer-v1", JSON.stringify({ state: {}, version: 1 }));

    await expect(useTrayDrawerStore.persist.rehydrate()).resolves.not.toThrow();

    expect(useTrayDrawerStore.getState().open).toBe(false);
  });
});
