import { useQuery } from "@tanstack/react-query";
import { getHealth } from "../api/client";

const STALE_TIME_MS = 60_000;

/** GET /api/health (task 4.2's Diagnostics page "App" section) -- also
 * doubles as this app's own "is the backend reachable at all" probe:
 * `isError` here means the fetch itself failed, not just that some feature
 * is misconfigured (health has no failure modes of its own, see main.py's
 * handler). staleTime mirrors useHomeboxStatus's own "not Infinity, but not
 * every render either" convention. */
export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: getHealth, staleTime: STALE_TIME_MS });
}
