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
          png_width_px: 200,
          png_height_px: 96,
          length_mm: 25.4,
          warnings: [],
        });
      }),
    );

    vi.useFakeTimers();
    try {
      const { rerender } = renderHook(({ definition }) => usePreview(definition), {
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
          png_width_px: 200,
          png_height_px: 96,
          length_mm: 25.4,
          warnings: [
            {
              code: "text_truncated",
              severity: "warning",
              message: "text truncated: content is wider than the fixed label length",
              object_id: null,
            },
          ],
        }),
      ),
    );

    const { result } = renderHook(() => usePreview(definitionWithText("HELLO")), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.png).not.toBeNull());
    expect(result.current.png).toBe(`data:image/png;base64,${TINY_PNG_B64}`);
    expect(result.current.lengthMm).toBe(25.4);
    expect(result.current.warnings).toEqual([
      {
        code: "text_truncated",
        severity: "warning",
        message: "text truncated: content is wider than the fixed label length",
        object_id: null,
      },
    ]);
  });

  // I2: regression test for the first-keystroke 422 flash. Sequence: mount
  // with an EMPTY form, let `debounced` settle onto that empty definition
  // (mirrors a user loading the page and pausing before typing), THEN type
  // the first character. At that instant the LIVE definition is already
  // renderable, but `debounced` hasn't caught up yet -- with the query
  // gated on the live value (the pre-fix behavior), that fires a request
  // against the still-empty `debounced` and 422s. Gating on `debounced`
  // itself (the fix) must produce zero requests until ITS OWN debounce
  // window elapses with renderable content.
  it("fires no request against a stale empty debounced value on the first keystroke (I2)", async () => {
    const requestSpy = vi.fn<(lines: string[]) => void>();
    server.use(
      http.post("/api/render/preview", async ({ request }) => {
        const body = (await request.json()) as { definition: LabelDefinition };
        const lines = (body.definition.params as { lines: string[] }).lines;
        requestSpy(lines);
        const renderable = lines.some((line) => line.trim() !== "");
        if (!renderable) {
          return HttpResponse.json({ detail: "labels: at least one non-blank line" }, { status: 422 });
        }
        return HttpResponse.json({
          png_b64: TINY_PNG_B64,
          png_width_px: 200,
          png_height_px: 96,
          length_mm: 25.4,
          warnings: [],
        });
      }),
    );

    vi.useFakeTimers();
    try {
      const { rerender } = renderHook(({ definition }) => usePreview(definition), {
        initialProps: { definition: definitionWithText("") },
        wrapper: createWrapper(),
      });

      // Let the empty initial definition settle into `debounced`.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(300);
      });
      expect(requestSpy).not.toHaveBeenCalled();

      // First keystroke: live definition is renderable now, `debounced`
      // isn't yet -- must NOT fire against the stale empty value.
      rerender({ definition: definitionWithText("H") });
      expect(requestSpy).not.toHaveBeenCalled();

      // Only once the NEW debounce window elapses (now with renderable
      // content) should a request fire -- and it must be a 200, never 422.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(300);
      });
    } finally {
      vi.useRealTimers();
    }

    await waitFor(() => expect(requestSpy).toHaveBeenCalledTimes(1));
    expect(requestSpy).toHaveBeenCalledWith(["H"]);
  });
});
