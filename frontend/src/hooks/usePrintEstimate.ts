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
  definition: LabelDefinition;
  options: PrintOptions;
  serialization: Sequence | null;
}

/** POST /api/print/estimate (task 2.9), debounced the same way usePreview
 * debounces /api/render/preview -- the Job Tray's "how much tape will this
 * use?" readout, refetched whenever the definition OR the chosen chain
 * mode/margin/auto-cut changes. Never creates a job (no history entry,
 * nothing enqueued) -- see router_print.py's estimate_print_job.
 *
 * The placeholder bridge (keeping the last estimate visible while a new
 * one loads) is scoped to the SAME label type only, via `debounced.
 * definition.type` as its own queryKey segment -- see usePreview.ts's own
 * (more detailed) docstring for why: this hook's useQuery observer
 * likewise persists across a label-type switch, and the built-in
 * `keepPreviousData` would otherwise carry one type's last estimate into a
 * freshly-switched type's still-loading state.
 *
 * `serialization` (task 2.11, optional, default null): when non-null, the
 * SAME (single-template-label) request POST /api/print/estimate expands
 * server-side into the full run's estimate -- see api/types.ts's
 * PrintRequest doc. Callers are expected to only pass a `serialization`
 * that's already confirmed printable (hooks/useSequenceExpand.ts). */
export function usePrintEstimate(
  definition: LabelDefinition,
  options: PrintOptions,
  isRenderable: (definition: LabelDefinition) => boolean,
  serialization: Sequence | null = null,
): UsePrintEstimateResult {
  const [debounced, setDebounced] = useState<DebouncedInput | undefined>(undefined);

  useEffect(() => {
    const handle = setTimeout(() => setDebounced({ definition, options, serialization }), DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(definition), JSON.stringify(options), JSON.stringify(serialization)]);

  const enabled = debounced !== undefined && isRenderable(debounced.definition);
  const debouncedType = debounced?.definition.type ?? null;

  const query = useQuery({
    queryKey: ["print-estimate", debouncedType, debounced ? JSON.stringify(debounced) : null],
    queryFn: () =>
      postPrintEstimate({
        labels: [debounced!.definition],
        options: debounced!.options,
        serialization: debounced!.serialization ?? undefined,
      }),
    enabled,
    placeholderData: (previousData, previousQuery) =>
      debouncedType !== null && previousQuery?.queryKey?.[1] === debouncedType ? previousData : undefined,
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
