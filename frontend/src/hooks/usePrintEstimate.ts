import { useEffect, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ApiError, postPrintEstimate } from "../api/client";
import type { LabelDefinition, PrintEstimateResponse, PrintOptions } from "../api/types";

const DEBOUNCE_MS = 300;

export interface UsePrintEstimateResult {
  estimate: PrintEstimateResponse | null;
  isFetching: boolean;
  error: string | null;
}

interface DebouncedInput {
  definition: LabelDefinition;
  options: PrintOptions;
}

/** POST /api/print/estimate (task 2.9), debounced the same way usePreview
 * debounces /api/render/preview -- the Job Tray's "how much tape will this
 * use?" readout, refetched whenever the definition OR the chosen chain
 * mode/margin/auto-cut changes. Never creates a job (no history entry,
 * nothing enqueued) -- see router_print.py's estimate_print_job. */
export function usePrintEstimate(
  definition: LabelDefinition,
  options: PrintOptions,
  isRenderable: (definition: LabelDefinition) => boolean,
): UsePrintEstimateResult {
  const [debounced, setDebounced] = useState<DebouncedInput | undefined>(undefined);

  useEffect(() => {
    const handle = setTimeout(() => setDebounced({ definition, options }), DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(definition), JSON.stringify(options)]);

  const enabled = debounced !== undefined && isRenderable(debounced.definition);

  const query = useQuery({
    queryKey: ["print-estimate", debounced ? JSON.stringify(debounced) : null],
    queryFn: () => postPrintEstimate({ labels: [debounced!.definition], options: debounced!.options }),
    enabled,
    placeholderData: keepPreviousData,
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
