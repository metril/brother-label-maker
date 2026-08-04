import { describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { setMediaQueryMatches } from "../test/setup";
import { DESKTOP_QUERY, useIsDesktop } from "./useIsDesktop";

describe("useIsDesktop", () => {
  it("defaults to false when the desktop query hasn't matched", () => {
    const { result } = renderHook(() => useIsDesktop());
    expect(result.current).toBe(false);
  });

  it("reads a query that already matches before mount -- true on first render", () => {
    setMediaQueryMatches(DESKTOP_QUERY, true);
    const { result } = renderHook(() => useIsDesktop());
    expect(result.current).toBe(true);
  });

  it("flips reactively when the query changes after mount, both directions", () => {
    const { result } = renderHook(() => useIsDesktop());
    expect(result.current).toBe(false);

    act(() => setMediaQueryMatches(DESKTOP_QUERY, true));
    expect(result.current).toBe(true);

    act(() => setMediaQueryMatches(DESKTOP_QUERY, false));
    expect(result.current).toBe(false);
  });

  it("removes its change listener on unmount -- further setMediaQueryMatches calls don't warn or throw", () => {
    const { unmount } = renderHook(() => useIsDesktop());
    unmount();

    expect(() => act(() => setMediaQueryMatches(DESKTOP_QUERY, true))).not.toThrow();
  });
});
