import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getSettings, putSettings } from "../api/client";
import type { SettingsUpdate } from "../api/types";

export const SETTINGS_QUERY_KEY = ["settings"] as const;

const STALE_TIME_MS = 60_000;

/** GET /api/settings (task 4.5) -- the Settings page's single source for
 * every editable + read-only row. A short staleTime (not Infinity, mirrors
 * the old useRuntimeSettings hook this replaces): a change made from a
 * different browser tab/session shows up on a revisit without a hard
 * refresh. */
export function useSettingsQuery() {
  return useQuery({ queryKey: SETTINGS_QUERY_KEY, queryFn: getSettings, staleTime: STALE_TIME_MS });
}

/** PUT /api/settings -- on success, writes the response straight into the
 * ["settings"] query cache (the server already returns the fresh full
 * body, including any OTHER row whose provenance might have shifted as a
 * side effect) rather than triggering a refetch. */
export function useUpdateSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (partial: SettingsUpdate) => putSettings(partial),
    onSuccess: (data) => {
      queryClient.setQueryData(SETTINGS_QUERY_KEY, data);
    },
  });
}
