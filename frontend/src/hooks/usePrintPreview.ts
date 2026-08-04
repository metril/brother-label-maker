import { useQuery } from "@tanstack/react-query";
import { ApiError, postPrintPreview } from "../api/client";
import type { ChainedPreviewResponse, LabelDefinition, PrintOptions } from "../api/types";

/** Matches the backend's default PrintPreviewRequest.scale
 * (router_print.py) -- kept fixed here the same way hooks/usePreview.ts's
 * own PREVIEW_SCALE is: ChainedPreviewDialog's zoom control is a pure
 * client-side px-per-mm concern (the strip's `<img>` is stretched to an
 * explicit CSS width/height regardless of the PNG's own native pixel
 * size, same as FeedDeck's DeckStrip), never threaded into this scale. */
const PREVIEW_SCALE = 2;

export interface UsePrintPreviewResult {
  preview: ChainedPreviewResponse | null;
  isFetching: boolean;
  error: string | null;
}

/** POST /api/print/preview (Track C2) -- PrintPreviewDeck's own data
 * source. Deliberately NOT debounced the way usePrintEstimate/usePreview
 * are: those debounce keystroke-level churn on `labels` itself, but this
 * hook's `labels`/`options` only ever change from a discrete click (a
 * tray-side `useTrayStore.chainMode` change via TrayPanel.tsx's own Mode
 * control, a tray edit, or opening the drawer in the first place) -- a
 * debounce window would just add a visible delay to an explicit user
 * action with nothing to coalesce.
 *
 * `queryKey` mirrors TrayPanel's own `bodyKey` convention (a single
 * `JSON.stringify` of the whole body) -- `options` already carries
 * `chain_mode`, so a `chainMode` change from TrayPanel's own Mode control
 * changes the key (and therefore refetches) the same way editing the tray
 * body does. No `serialization` field: PrintPreviewDeck.tsx's own labels
 * come solely from stores/tray.ts's queued items, and a tray item never
 * carries a serialization run (that's a Designer-page, single-design
 * concept) -- see that component's own docstring for why the
 * empty-tray-falls-back-to-the-current-design behavior this hook used to
 * support was removed entirely.
 *
 * `enabled` requires BOTH `open` (no reason to pay for a full render pass
 * while the drawer is closed -- this endpoint is real render work, unlike
 * the estimate-only one it mirrors) AND `isRenderable(labels)` -- the same
 * "match the debounced/current value, not a stale one" gate
 * usePrintEstimate/usePreview apply to their own queries, reused here
 * as-is since TrayPanel already computes it for the estimate query. */
export function usePrintPreview(
  labels: LabelDefinition[],
  options: PrintOptions,
  isRenderable: (labels: LabelDefinition[]) => boolean,
  open: boolean,
): UsePrintPreviewResult {
  const enabled = open && isRenderable(labels);
  // Skip the JSON.stringify entirely while closed (L13 review fix): the
  // drawer stays mounted (see PrintPreviewDeck.tsx's own docstring) and
  // subscribes to the live tray, so without this a closed drawer still
  // re-stringifies its whole request body on every keystroke elsewhere in
  // the app (e.g. the Design route) for a query that `enabled` above never
  // even runs. The literal "closed" value is never compared against a real
  // bodyKey -- `enabled` alone gates the fetch -- it only needs to be
  // constant so toggling `open` closed doesn't itself look like a
  // query-key change.
  const bodyKey = open ? JSON.stringify({ labels, options }) : "closed";

  const query = useQuery({
    queryKey: ["print-preview", bodyKey],
    queryFn: () =>
      postPrintPreview({
        labels,
        options,
        scale: PREVIEW_SCALE,
      }),
    enabled,
    retry: false,
    staleTime: Infinity,
  });

  const error = query.error
    ? query.error instanceof ApiError
      ? query.error.message
      : "preview request failed"
    : null;

  return { preview: query.data ?? null, isFetching: query.isFetching, error };
}
