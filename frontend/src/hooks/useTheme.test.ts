import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useTheme } from "./useTheme";

describe("useTheme", () => {
  it("defaults to \"dark\" when localStorage has no stored preference -- this app's identity is dark, not system", () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe("dark");
  });

  it("treats any stored value other than \"light\"/\"system\" as dark -- mirrors index.html's own pre-paint script", () => {
    localStorage.setItem("lm-theme", "not-a-real-theme");
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe("dark");
  });

  it("setTheme(\"light\") persists to localStorage and sets <html data-theme=\"light\">", () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setTheme("light"));

    expect(result.current.theme).toBe("light");
    expect(localStorage.getItem("lm-theme")).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("setTheme(\"system\") persists to localStorage and REMOVES the data-theme attribute (the CSS media query governs instead)", () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setTheme("dark"));
    expect(document.documentElement.hasAttribute("data-theme")).toBe(true);

    act(() => result.current.setTheme("system"));
    expect(result.current.theme).toBe("system");
    expect(localStorage.getItem("lm-theme")).toBe("system");
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });

  it("every mounted consumer observes the same theme -- one hook instance's setTheme updates another's snapshot", () => {
    const a = renderHook(() => useTheme());
    const b = renderHook(() => useTheme());

    act(() => a.result.current.setTheme("light"));

    expect(a.result.current.theme).toBe("light");
    expect(b.result.current.theme).toBe("light");
  });

  describe("localStorage guarded against throwing (L15 -- blocked site data throws SecurityError, no ErrorBoundary above this hook)", () => {
    afterEach(() => {
      vi.restoreAllMocks();
    });

    it("falls back to \"dark\" instead of propagating when localStorage.getItem throws", () => {
      vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
        throw new DOMException("blocked", "SecurityError");
      });

      const { result } = renderHook(() => useTheme());
      expect(result.current.theme).toBe("dark");
    });

    it("setTheme swallows a throwing localStorage.setItem instead of propagating -- <html data-theme> still updates for this tab", () => {
      vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
        throw new DOMException("blocked", "SecurityError");
      });

      const { result } = renderHook(() => useTheme());
      expect(() => act(() => result.current.setTheme("light"))).not.toThrow();
      expect(document.documentElement.dataset.theme).toBe("light");
    });
  });
});
