import { useEffect, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ApiError, pngDataUrl, postPreview } from "../api/client";
import { hasRenderableContent } from "../stores/designer";
import type { LabelDefinition, RenderWarning, TextLabelParams } from "../api/types";

const DEBOUNCE_MS = 300;
/** Matches the backend's default PreviewRequest.scale (router_labels.py) --
 * kept fixed here since the UI never lets the user pick a scale. */
const PREVIEW_SCALE = 2;

export interface UsePreviewResult {
  /** data: URL of the decoded preview PNG, or null before the first result. */
  png: string | null;
  /** Physical label length in mm -- ALWAYS read from the response's
   * `length_mm` field, never derived from png_width_px/png_height_px
   * (those are scaled device-dot dimensions; see api/types.ts's
   * PreviewResponse doc). */
  lengthMm: number | null;
  warnings: RenderWarning[];
  isFetching: boolean;
  error: string | null;
}

/** Debounces `definition` by 300ms before firing /api/render/preview, so a
 * burst of keystrokes/param changes collapses into a single request instead
 * of one per change. The previous image is kept on screen (placeholderData:
 * keepPreviousData) while a new one loads, so the preview never flashes
 * blank between renders -- only `isFetching` flips, for a subtle indicator. */
export function usePreview(definition: LabelDefinition): UsePreviewResult {
  // Starts undefined (not seeded with `definition`) so the FIRST value is
  // debounced exactly like every subsequent one -- otherwise the initial
  // render would fire an immediate, un-debounced request before the 300ms
  // window ever applied.
  const [debounced, setDebounced] = useState<LabelDefinition | undefined>(undefined);

  useEffect(() => {
    const handle = setTimeout(() => setDebounced(definition), DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // definition is a fresh object per render by design (designer store
    // selectors); comparing its serialized form is what actually matters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(definition)]);

  // I2: gate strictly on the DEBOUNCED value's renderability, not the live
  // `definition` passed in on every keystroke. The query itself always
  // fires against `debounced`, so gating on the live value is wrong: it can
  // go true (first keystroke turns the form non-blank) before `debounced`
  // has caught up (it's still whatever settled 300ms ago, possibly the
  // still-blank initial state) -- firing a request against that stale,
  // non-renderable `debounced` and 422-ing for one query cycle.
  const isRenderable =
    debounced !== undefined && hasRenderableContent(debounced.params as TextLabelParams);

  const query = useQuery({
    queryKey: ["preview", debounced ? JSON.stringify(debounced) : null, PREVIEW_SCALE],
    queryFn: () => postPreview({ definition: debounced as LabelDefinition, scale: PREVIEW_SCALE }),
    enabled: isRenderable,
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: Infinity,
  });

  const error = query.error
    ? query.error instanceof ApiError
      ? query.error.message
      : "preview request failed"
    : null;

  return {
    png: query.data ? pngDataUrl(query.data.png_b64) : null,
    lengthMm: query.data?.length_mm ?? null,
    warnings: query.data?.warnings ?? [],
    isFetching: query.isFetching,
    error,
  };
}
