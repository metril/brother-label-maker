import { afterEach, describe, expect, it } from "vitest";
import { useChainPreviewStore } from "./chainPreview";

const INITIAL_STATE = useChainPreviewStore.getState();

afterEach(() => {
  useChainPreviewStore.setState(INITIAL_STATE, true);
});

describe("useChainPreviewStore", () => {
  it("openDrawer/closeDrawer/toggle flip `open` only", () => {
    expect(useChainPreviewStore.getState().open).toBe(false);

    useChainPreviewStore.getState().openDrawer();
    expect(useChainPreviewStore.getState().open).toBe(true);

    useChainPreviewStore.getState().closeDrawer();
    expect(useChainPreviewStore.getState().open).toBe(false);

    useChainPreviewStore.getState().toggle();
    expect(useChainPreviewStore.getState().open).toBe(true);
    useChainPreviewStore.getState().toggle();
    expect(useChainPreviewStore.getState().open).toBe(false);
  });

  it("toggleDocked flips `docked` only, defaulting to false", () => {
    expect(useChainPreviewStore.getState().docked).toBe(false);

    useChainPreviewStore.getState().toggleDocked();
    expect(useChainPreviewStore.getState().docked).toBe(true);
    expect(useChainPreviewStore.getState().open).toBe(false);

    useChainPreviewStore.getState().toggleDocked();
    expect(useChainPreviewStore.getState().docked).toBe(false);
  });
});

/** `docked` alone is persisted (zustand's `persist` middleware, key
 * "lm-chain-preview-v1") -- see the store's own docstring for why: it's a
 * standing layout preference, unlike `open`, which stays purely
 * in-memory/session-only the same way it always has. */
describe("useChainPreviewStore persistence (zustand persist middleware)", () => {
  it("partialize writes `docked` (and only `docked`) to localStorage", () => {
    useChainPreviewStore.getState().toggleDocked();

    const raw = localStorage.getItem("lm-chain-preview-v1");
    expect(raw).not.toBeNull();
    const persisted = JSON.parse(raw!) as { state: Record<string, unknown> };
    expect(persisted.state).toEqual({ docked: true });
  });

  it("`open` never reaches localStorage, even while true", () => {
    useChainPreviewStore.getState().openDrawer();
    useChainPreviewStore.getState().toggleDocked();

    const raw = localStorage.getItem("lm-chain-preview-v1");
    const persisted = JSON.parse(raw!) as { state: Record<string, unknown> };
    expect(persisted.state).not.toHaveProperty("open");
  });

  it("rehydrates `docked` from a previously persisted snapshot, leaving `open` at its own default", async () => {
    localStorage.setItem(
      "lm-chain-preview-v1",
      JSON.stringify({ state: { docked: true }, version: 1 }),
    );

    await useChainPreviewStore.persist.rehydrate();

    const state = useChainPreviewStore.getState();
    expect(state.docked).toBe(true);
    expect(state.open).toBe(false);
  });
});
