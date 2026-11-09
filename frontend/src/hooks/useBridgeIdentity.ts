import { useQuery } from "@tanstack/react-query";
import { getBridgeIdentity } from "../api/client";

/** This app's public bridge certificate; only fetched while the Settings
 * page is showing the remote-printer fields (the server generates the
 * keypair on first request, so don't ask unless it's needed). */
export function useBridgeIdentity(enabled: boolean) {
  return useQuery({
    queryKey: ["bridge-identity"],
    queryFn: getBridgeIdentity,
    enabled,
    staleTime: Infinity,
  });
}
