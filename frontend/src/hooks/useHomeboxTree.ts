import { useQuery } from "@tanstack/react-query";
import { getHomeboxTree } from "../api/client";

/** GET /api/homebox/entities/tree (task 3.4), locations only (`with_items`
 * left at its default false) -- the browse page's own left rail. `enabled`
 * lets the page skip the network call entirely while HomeBox isn't a
 * configured+healthy data source yet (unconfigured / unreachable states) --
 * see pages/Homebox.tsx. */
export function useHomeboxTree(enabled: boolean) {
  return useQuery({
    queryKey: ["homebox-tree"],
    queryFn: () => getHomeboxTree(false),
    enabled,
  });
}
