import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ApiError, postPrintEstimate } from "../api/client";
import type { LabelDefinition, PrintEstimateResponse, PrintOptions, Sequence } from "../api/types";

const DEBOUNCE_MS = 300;

export interface UsePrintEstimateResult {
  estimate: PrintEstimateResponse | null;
  isFetching: boolean;
  error: string | null;
}

interface DebouncedInput {
  labels: LabelDefinition[];
  options: PrintOptions;
  serialization: Sequence | null;
}

/** POST /api/print/estimate (task 2.9), debounced the same way usePreview
 * debounces /api/render/preview -- the Job Tray's "how much tape will this
 * use?" readout, refetched whenever the label set OR the chosen chain
 * mode/margin/auto-cut changes. Never creates a job (no history entry,
 * nothing enqueued) -- see router_print.py's estimate_print_job.
 *
 * `labels` (task 2.12, generalized from the single-`definition` shape task
 * 2.9-2.11 had): the SAME `labels` array POST /api/print's own body takes --
 * either the tray's own item definitions, or a one-element array wrapping
 * the current (unsaved) design when the tray is empty (see JobTray.tsx's
 * own `bodyLabels`). `isRenderable` is applied to the DEBOUNCED value, not
 * the live one (the same I2 class of bug usePreview.ts documents and
 * guards against), so callers pass a predicate over the labels array, e.g.
 * `(labels) => labels.length > 0`.
 *
 * The placeholder bridge (keeping the last estimate visible while a new one
 * loads) is scoped by the debounced labels' own JOINED `type` list, via
 * `debouncedTypeKey` as its own queryKey segment -- see usePreview.ts's own
 * (more detailed) docstring for why: this hook's useQuery observer likewise
 * persists across the tray/current-design changing shape entirely (e.g. an
 * empty tray gaining its first item, or a label type switch), and the
 * built-in `keepPreviousData` would otherwise carry one shape's last
 * estimate into a freshly-changed shape's still-loading state.
 *
 * `serialization` (task 2.11, optional, default null): non-null only for
 * the empty-tray/single-template path -- the tray's own multi-item path
 * never sends one (they're mutually exclusive server-side; see
 * JobTray.tsx). Callers are expected to only pass a `serialization` that's
 * already confirmed printable (hooks/useSequenceExpand.ts). */
export function usePrintEstimate(
  labels: LabelDefinition[],
  options: PrintOptions,
  isRenderable: (labels: LabelDefinition[]) => boolean,
  serialization: Sequence | null = null,
): UsePrintEstimateResult {
  const [debounced, setDebounced] = useState<DebouncedInput | undefined>(undefined);

  useEffect(() => {
    const handle = setTimeout(() => setDebounced({ labels, options, serialization }), DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(labels), JSON.stringify(options), JSON.stringify(serialization)]);

  const enabled = debounced !== undefined && isRenderable(debounced.labels);
  const debouncedTypeKey = debounced ? debounced.labels.map((l) => l.type).join(",") : null;

  const query = useQuery({
    queryKey: ["print-estimate", debouncedTypeKey, debounced ? JSON.stringify(debounced) : null],
    queryFn: ({ signal }) =>
      postPrintEstimate(
        {
          labels: debounced!.labels,
          options: debounced!.options,
          serialization: debounced!.serialization ?? undefined,
        },
        signal,
      ),
    enabled,
    placeholderData: (previousData, previousQuery) =>
      debouncedTypeKey !== null && previousQuery?.queryKey?.[1] === debouncedTypeKey ? previousData : undefined,
    retry: false,
    staleTime: Infinity,
  });

  const error = query.error
    ? query.error instanceof ApiError
      ? query.error.message
      : "estimate request failed"
    : null;

  return { estimate: query.data ?? null, isFetching: query.isFetching, error };
}
