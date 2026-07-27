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

/** Mirrors text_label.py's own "at least one non-blank line" gate --
 * usePreview is type-generic now (task 2.10), so callers supply their own
 * predicate instead of it importing a text-only hasRenderableContent. */
function isRenderable(definition: LabelDefinition): boolean {
  const lines = (definition.params as { lines: string[] }).lines;
  return lines.some((line) => line.trim() !== "");
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
          min_feed_mm: 24.5,
          warnings: [],
        });
      }),
    );

    vi.useFakeTimers();
    try {
      const { rerender } = renderHook(({ definition }) => usePreview(definition, isRenderable), {
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

  it("returns a decoded png data URL, min_feed_mm, and warnings from the response", async () => {
    server.use(
      http.post("/api/render/preview", () =>
        HttpResponse.json({
          png_b64: TINY_PNG_B64,
          png_width_px: 200,
          png_height_px: 96,
          length_mm: 25.4,
          min_feed_mm: 24.5,
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

    const { result } = renderHook(() => usePreview(definitionWithText("HELLO"), isRenderable), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.png).not.toBeNull());
    expect(result.current.png).toBe(`data:image/png;base64,${TINY_PNG_B64}`);
    expect(result.current.lengthMm).toBe(25.4);
    expect(result.current.minFeedMm).toBe(24.5);
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
          min_feed_mm: 24.5,
          warnings: [],
        });
      }),
    );

    vi.useFakeTimers();
    try {
      const { rerender } = renderHook(({ definition }) => usePreview(definition, isRenderable), {
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

  // Regression test (task 2.10 review): the hook's underlying useQuery
  // observer persists across a label-TYPE switch (Designer.tsx calls
  // usePreview once, for whichever type is currently selected) -- the
  // built-in keepPreviousData placeholder bridges an observer's data
  // across ANY key change, so switching from "text" to "barcode" used to
  // keep showing text's own last png/lengthMm/warnings until barcode's OWN
  // fetch resolved, contradicting the type actually on screen.
  it(
    "does not carry a previous label TYPE's data forward while a DIFFERENT type's request is still in flight",
    async () => {
      let releaseBarcode: (() => void) | undefined;
      server.use(
        http.post("/api/render/preview", async ({ request }) => {
          const body = (await request.json()) as { definition: LabelDefinition };
          if (body.definition.type === "barcode") {
            await new Promise<void>((resolve) => {
              releaseBarcode = resolve;
            });
            return HttpResponse.json({
              png_b64: TINY_PNG_B64,
              png_width_px: 100,
              png_height_px: 96,
              length_mm: 12.0,
              min_feed_mm: 24.5,
              warnings: [],
            });
          }
          return HttpResponse.json({
            png_b64: TINY_PNG_B64,
            png_width_px: 200,
            png_height_px: 96,
            length_mm: 25.4,
            min_feed_mm: 24.5,
            warnings: [],
          });
        }),
      );

      const alwaysRenderable = () => true;
      const { result, rerender } = renderHook(({ definition }) => usePreview(definition, alwaysRenderable), {
        initialProps: { definition: definitionWithText("HELLO") },
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.lengthMm).toBe(25.4), { timeout: 2000 });

      const barcodeDefinition: LabelDefinition = {
        type: "barcode",
        tape: { width_mm: 24, family: "tze" },
        params: { data: "X" },
      };
      rerender({ definition: barcodeDefinition });

      // The barcode fetch is now in flight, deliberately held open -- this
      // is exactly the moment the old (buggy) behavior would still show
      // "text"'s stale 25.4mm/png. It must show nothing instead.
      await waitFor(() => expect(result.current.isFetching).toBe(true), { timeout: 2000 });
      expect(result.current.lengthMm).toBeNull();
      expect(result.current.png).toBeNull();

      releaseBarcode?.();
      await waitFor(() => expect(result.current.lengthMm).toBe(12.0), { timeout: 2000 });
    },
    10_000,
  );

  // Regression (task 2.10 review, fix round 2): the ABOVE test only checks
  // the state once the debounce has already settled onto the new type --
  // it doesn't catch a bug where `debounced` (and therefore debouncedType/
  // the query key) keeps pointing at the OLD type for the ~300ms BETWEEN
  // the type switch and the debounce firing. Designer.tsx's heading reads
  // `definition.type` directly (undebounced), so during that window the
  // heading already reads the new type while the deck kept rendering the
  // previous type's own last-successful png/lengthMm/warnings. This test
  // asserts the state IMMEDIATELY after the type switch, before letting any
  // time pass.
  it("clears the previous type's png/lengthMm the instant the label TYPE changes, before the new debounce window elapses", async () => {
    server.use(
      http.post("/api/render/preview", async ({ request }) => {
        const body = (await request.json()) as { definition: LabelDefinition };
        if (body.definition.type === "barcode") {
          return HttpResponse.json({
            png_b64: TINY_PNG_B64,
            png_width_px: 100,
            png_height_px: 96,
            length_mm: 12.0,
            min_feed_mm: 24.5,
            warnings: [],
          });
        }
        return HttpResponse.json({
          png_b64: TINY_PNG_B64,
          png_width_px: 200,
          png_height_px: 96,
          length_mm: 25.4,
          min_feed_mm: 24.5,
          warnings: [],
        });
      }),
    );

    const alwaysRenderable = () => true;
    const { result, rerender } = renderHook(({ definition }) => usePreview(definition, alwaysRenderable), {
      initialProps: { definition: definitionWithText("HELLO") },
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.lengthMm).toBe(25.4));

    const barcodeDefinition: LabelDefinition = {
      type: "barcode",
      tape: { width_mm: 24, family: "tze" },
      params: { data: "X" },
    };
    rerender({ definition: barcodeDefinition });

    // No waitFor, no timer advance -- still well inside the 300ms debounce
    // window. The old ("text") readouts must already be gone, not lingering
    // until `debounced` catches up.
    expect(result.current.lengthMm).toBeNull();
    expect(result.current.png).toBeNull();
  });
});
