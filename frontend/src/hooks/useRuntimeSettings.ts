import { useQuery } from "@tanstack/react-query";
import { getRuntimeSettings } from "../api/client";

const STALE_TIME_MS = 60_000;

/** GET /api/settings/runtime (task 4.2's Settings page read-only config
 * panel) -- env-derived, so it only actually changes on a restart; a short
 * staleTime (not Infinity) just means a page revisit after a redeploy
 * shows the current values without a hard refresh. */
export function useRuntimeSettings() {
  return useQuery({ queryKey: ["runtime-settings"], queryFn: getRuntimeSettings, staleTime: STALE_TIME_MS });
}
