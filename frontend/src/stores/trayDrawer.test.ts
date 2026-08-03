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

  it("toggleDocked flips `docked` only, defaulting to false", () => {
    expect(useTrayDrawerStore.getState().docked).toBe(false);

    useTrayDrawerStore.getState().toggleDocked();
    expect(useTrayDrawerStore.getState().docked).toBe(true);
    expect(useTrayDrawerStore.getState().open).toBe(false);

    useTrayDrawerStore.getState().toggleDocked();
    expect(useTrayDrawerStore.getState().docked).toBe(false);
  });
});

/** `docked` alone is persisted (zustand's `persist` middleware, key
 * "lm-tray-drawer-v1") -- see the store's own docstring for why: it's a
 * standing layout preference, unlike `open`, which stays purely
 * in-memory/session-only. */
describe("useTrayDrawerStore persistence (zustand persist middleware)", () => {
  it("partialize writes `docked` (and only `docked`) to localStorage", () => {
    useTrayDrawerStore.getState().toggleDocked();

    const raw = localStorage.getItem("lm-tray-drawer-v1");
    expect(raw).not.toBeNull();
    const persisted = JSON.parse(raw!) as { state: Record<string, unknown> };
    expect(persisted.state).toEqual({ docked: true });
  });

  it("`open` never reaches localStorage, even while true", () => {
    useTrayDrawerStore.getState().openDrawer();
    useTrayDrawerStore.getState().toggleDocked();

    const raw = localStorage.getItem("lm-tray-drawer-v1");
    const persisted = JSON.parse(raw!) as { state: Record<string, unknown> };
    expect(persisted.state).not.toHaveProperty("open");
  });

  it("rehydrates `docked` from a previously persisted snapshot, leaving `open` at its own default", async () => {
    localStorage.setItem(
      "lm-tray-drawer-v1",
      JSON.stringify({ state: { docked: true }, version: 1 }),
    );

    await useTrayDrawerStore.persist.rehydrate();

    const state = useTrayDrawerStore.getState();
    expect(state.docked).toBe(true);
    expect(state.open).toBe(false);
  });
});
