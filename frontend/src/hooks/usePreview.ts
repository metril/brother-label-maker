import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ApiError, pngDataUrl, postPreview } from "../api/client";
import type { LabelDefinition, RenderWarning } from "../api/types";

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
  minFeedMm: number | null;
  warnings: RenderWarning[];
  isFetching: boolean;
  error: string | null;
}

/** Debounces `definition` by 300ms before firing /api/render/preview, so a
 * burst of keystrokes/param changes collapses into a single request instead
 * of one per change. The previous image is kept on screen while a new one
 * loads (a `placeholderData` function, not the built-in `keepPreviousData`
 * helper) so the preview never flashes blank between renders -- only
 * `isFetching` flips, for a subtle indicator.
 *
 * That bridge is scoped to the SAME label type only: Designer.tsx keeps
 * this same usePreview() call (and therefore the same underlying useQuery
 * observer) mounted across a label-TYPE switch, not just across param
 * edits within one type -- `keepPreviousData` bridges an observer's data
 * across ANY key change with no such distinction, so it used to carry a
 * "text" label's last png/lengthMm/warnings into a freshly-selected
 * "punch_down" label's still-loading initial render, showing numbers that
 * described the wrong type. `definition.type` is threaded into the
 * queryKey as its own segment specifically so this comparison is a direct
 * equality check, not a re-parse of the debounced JSON blob.
 *
 * `isRenderable` decides whether the (debounced) definition is even worth
 * sending -- type-generic (task 2.10: every one of the 9 label types has
 * its own notion of "has enough content to preview", see
 * schema/renderable.ts's hasRenderableContent), unlike the text-only
 * hasRenderableContent this hook used to import directly. */
export function usePreview(
  definition: LabelDefinition,
  isRenderable: (definition: LabelDefinition) => boolean,
): UsePreviewResult {
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

  // Drop `debounced` the INSTANT the label TYPE itself changes, rather than
  // waiting out the 300ms window above. Designer.tsx's heading reads
  // `definition.type` directly (undebounced) -- without this, `debounced`
  // (and therefore debouncedType/the query key/query.data below) keeps
  // pointing at the OLD type for up to one full debounce window after the
  // heading already switched, so the deck goes on rendering the previous
  // type's png/lengthMm/warnings under the new type's heading.
  //
  // `useLayoutEffect`, not `useEffect`: both the heading and this hook's
  // return value are produced by the SAME render (Designer.tsx re-renders
  // once when `selectedType` changes, and calls usePreview() again in that
  // same pass) -- a plain `useEffect` only fires after the browser paints,
  // so it left a real (if brief -- ~15-40ms, one or two frames, measured
  // live) window where the new heading was already on screen next to the
  // old type's png. `useLayoutEffect` flushes synchronously before paint,
  // landing the clear in the SAME commit the heading itself changed in, so
  // there's no in-between frame to see.
  //
  // Scoped to `definition.type` alone (not the full JSON.stringify a param
  // edit would change) so ordinary editing within one type is untouched --
  // only an actual type switch resets debounced to undefined, which the
  // query's own `enabled`/`placeholderData` logic below already turns into
  // "no data, not fetching" until the debounce settles again on the new
  // type.
  const lastTypeRef = useRef<string | undefined>(undefined);
  useLayoutEffect(() => {
    if (lastTypeRef.current !== undefined && lastTypeRef.current !== definition.type) {
      setDebounced(undefined);
    }
    lastTypeRef.current = definition.type;
  }, [definition.type]);

  // I2: gate strictly on the DEBOUNCED value's renderability, not the live
  // `definition` passed in on every keystroke. The query itself always
  // fires against `debounced`, so gating on the live value is wrong: it can
  // go true (first keystroke turns the form non-blank) before `debounced`
  // has caught up (it's still whatever settled 300ms ago, possibly the
  // still-blank initial state) -- firing a request against that stale,
  // non-renderable `debounced` and 422-ing for one query cycle.
  const isDebouncedRenderable = debounced !== undefined && isRenderable(debounced);
  const debouncedType = debounced?.type ?? null;

  const query = useQuery({
    queryKey: ["preview", debouncedType, debounced ? JSON.stringify(debounced) : null, PREVIEW_SCALE],
    queryFn: () => postPreview({ definition: debounced as LabelDefinition, scale: PREVIEW_SCALE }),
    enabled: isDebouncedRenderable,
    placeholderData: (previousData, previousQuery) =>
      debouncedType !== null && previousQuery?.queryKey?.[1] === debouncedType ? previousData : undefined,
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
    minFeedMm: query.data?.min_feed_mm ?? null,
    warnings: query.data?.warnings ?? [],
    isFetching: query.isFetching,
    error,
  };
}
