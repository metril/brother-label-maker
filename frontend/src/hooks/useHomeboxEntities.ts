import { useQuery } from "@tanstack/react-query";
import { getHomeboxAssetMatches, getHomeboxEntities } from "../api/client";
import { matchesAssetIdShape, stripAssetIdHash } from "../lib/homebox";

interface UseHomeboxEntitiesParams {
  q?: string;
  page: number;
  pageSize: number;
  parentId?: string;
  enabled: boolean;
}

/** GET /api/homebox/entities (task 3.4), server-paginated + filtered by the
 * browse page's own search box (`q`) and selected location-tree node
 * (`parentId`) -- both combine server-side (router_homebox.py's
 * list_entities). `placeholderData` keeps the current page's rows on screen
 * across a page/filter change, the same convention useHistoryList already
 * uses. `enabled` mirrors useHomeboxTree's own -- skipped entirely until
 * HomeBox is a configured+healthy data source. */
export function useHomeboxEntities({ q, page, pageSize, parentId, enabled }: UseHomeboxEntitiesParams) {
  return useQuery({
    queryKey: ["homebox-entities", q ?? null, page, pageSize, parentId ?? null],
    queryFn: () => getHomeboxEntities({ q, page, page_size: pageSize, parent_id: parentId }),
    enabled,
    placeholderData: (previousData) => previousData,
  });
}

/** GET /api/homebox/assets/{id} (task 3.4) -- the "Asset ID matches"
 * disambiguation section, queried ALONGSIDE (not instead of) the normal
 * entities search whenever the raw search text looks like a HomeBox asset
 * id (lib/homebox.ts's matchesAssetIdShape). Zero/one/many results all
 * render (see pages/Homebox.tsx); a 404 from the proxy itself is already
 * normalized to an empty list server-side (homebox/client.py's
 * find_by_asset_id), so this hook never needs to special-case it. */
export function useHomeboxAssetMatches(rawQuery: string, enabled: boolean) {
  const isAssetIdShape = matchesAssetIdShape(rawQuery);
  const assetId = stripAssetIdHash(rawQuery);
  return useQuery({
    queryKey: ["homebox-asset-matches", assetId],
    queryFn: () => getHomeboxAssetMatches(assetId),
    enabled: enabled && isAssetIdShape,
  });
}
