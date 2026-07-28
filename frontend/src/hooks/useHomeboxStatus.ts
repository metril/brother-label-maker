import { useQuery } from "@tanstack/react-query";
import { getHomeboxStatus } from "../api/client";

const STALE_TIME_MS = 60_000;

/** GET /api/homebox/status (task 3.4) -- always-200 show/hide signal for
 * every HomeBox UI surface: AppShell's own nav item (a real NavLink vs the
 * disabled placeholder, see AppShell.tsx) and the /homebox page's own state
 * machine (unconfigured / unreachable-or-unhealthy / ready) both key off
 * this SAME query. staleTime is short, not Infinity like useTapes/useFonts'
 * static catalogs -- reachable/healthy can flip between visits (HomeBox
 * restarting, a rotated key) without a full page reload. */
export function useHomeboxStatus() {
  return useQuery({ queryKey: ["homebox-status"], queryFn: getHomeboxStatus, staleTime: STALE_TIME_MS });
}
