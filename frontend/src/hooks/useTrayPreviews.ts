import { useQueries } from "@tanstack/react-query";
import { pngDataUrl, postPreview } from "../api/client";
import type { TrayItem } from "../stores/tray";

export interface TrayPreview {
  png: string;
  lengthMm: number;
}

/** Fetches a preview for every tray item that doesn't already carry one
 * (`png === null`) -- namely items queued from somewhere other than the
 * Designer's live preview, e.g. pages/Homebox.tsx's "Add to tray" (task
 * 3.4), which has no rendered png/lengthMm on hand at add time. A tray
 * item's `definition` is a frozen snapshot the moment it's queued (see
 * stores/tray.ts's own TrayItem doc) -- its preview can never go stale, so
 * `staleTime: Infinity` + `retry: false` (same convention as usePreview.ts/
 * usePrintEstimate.ts): fetch once, keep forever, and don't hammer the
 * server retrying something that's fundamentally decorative.
 *
 * A 422 (or any other failure) leaves that item's id simply absent from the
 * returned map -- TrayItemRow's existing blank-swatch fallback (item.png ??
 * hydrated.get(item.id)?.png, both null/undefined) covers it silently,
 * exactly like an item that was never captured at all; there's no separate
 * error UI for a preview that's purely cosmetic (the item's own frozen
 * `definition` is what actually gets printed either way).
 *
 * Deliberately does NOT write the fetched png/lengthMm back into
 * stores/tray.ts -- that store is what gets persisted to localStorage (see
 * its own persist config), which explicitly nulls out png on write; a
 * refetched preview is cheap to derive from the frozen definition on
 * demand, so there's no reason to grow persisted storage with base64 PNGs
 * the store already refuses to keep. */
export function useTrayPreviews(items: TrayItem[]): Map<string, TrayPreview> {
  const targets = items.filter((item) => item.png === null);

  const results = useQueries({
    queries: targets.map((item) => ({
      queryKey: ["tray-preview", item.id],
      queryFn: () => postPreview({ definition: item.definition }),
      staleTime: Infinity,
      retry: false,
    })),
  });

  const previews = new Map<string, TrayPreview>();
  targets.forEach((item, i) => {
    const data = results[i]?.data;
    if (data) previews.set(item.id, { png: pngDataUrl(data.png_b64), lengthMm: data.length_mm });
  });
  return previews;
}
