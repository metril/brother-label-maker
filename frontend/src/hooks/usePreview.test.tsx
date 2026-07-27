import { describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { http, HttpResponse } from "msw";
import { usePreview } from "./usePreview";
import { server } from "../test/msw/server";
import { TINY_PNG_B64 } from "../test/msw/handlers";
import type { LabelDefinition } from "../api/types";

function createWrapper() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

function definitionWithText(text: string): LabelDefinition {
  return { type: "text", tape: { width_mm: 24, family: "tze" }, params: { lines: [text] } };
}

describe("usePreview", () => {
  it("debounces rapid definition changes into a single request, not one per keystroke", async () => {
    const requestSpy = vi.fn();
    server.use(
      http.post("/api/render/preview", () => {
        requestSpy();
        return HttpResponse.json({
          png_b64: TINY_PNG_B64,
          width_px: 200,
          height_px: 96,
          length_mm: 25.4,
          warnings: [],
        });
      }),
    );

    vi.useFakeTimers();
    try {
      const { rerender } = renderHook(({ definition }) => usePreview(definition, true), {
        initialProps: { definition: definitionWithText("H") },
        wrapper: createWrapper(),
      });

      // Three rapid changes within the debounce window -- only the last
      // should ever reach the network.
      rerender({ definition: definitionWithText("He") });
      rerender({ definition: definitionWithText("Hel") });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(300);
      });
    } finally {
      vi.useRealTimers();
    }

    await waitFor(() => expect(requestSpy).toHaveBeenCalledTimes(1));
  });

  it("returns a decoded png data URL and surfaces warnings from the response", async () => {
    server.use(
      http.post("/api/render/preview", () =>
        HttpResponse.json({
          png_b64: TINY_PNG_B64,
          width_px: 200,
          height_px: 96,
          length_mm: 25.4,
          warnings: ["text truncated: content is wider than the fixed label length"],
        }),
      ),
    );

    const { result } = renderHook(() => usePreview(definitionWithText("HELLO"), true), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.png).not.toBeNull());
    expect(result.current.png).toBe(`data:image/png;base64,${TINY_PNG_B64}`);
    expect(result.current.lengthMm).toBe(25.4);
    expect(result.current.warnings).toEqual([
      "text truncated: content is wider than the fixed label length",
    ]);
  });
});
