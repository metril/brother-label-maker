import { useQuery } from "@tanstack/react-query";
import { getHistory } from "../api/client";
import type { JobStatus } from "../api/types";

interface UseHistoryListParams {
  page: number;
  pageSize: number;
  status?: JobStatus;
  q?: string;
}

/** GET /api/history (task 2.13), paginated + filterable -- see
 * api/router_history.py's list_history (422s outside page>=1/
 * 1<=page_size<=100, which the History page's own controls stay within by
 * construction). `placeholderData` keeps the CURRENT page's rows on screen
 * while a page/filter change is in flight instead of the table flashing to
 * a loading state on every click -- the same "keep the last good result
 * visible" idea usePrintEstimate.ts already uses. */
export function useHistoryList({ page, pageSize, status, q }: UseHistoryListParams) {
  return useQuery({
    queryKey: ["history", page, pageSize, status ?? null, q ?? null],
    queryFn: () => getHistory({ page, page_size: pageSize, status, q }),
    placeholderData: (previousData) => previousData,
  });
}
