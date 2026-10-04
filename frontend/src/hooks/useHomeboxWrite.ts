import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getHomeboxEntityTypes, getHomeboxTags, postHomeboxBulkCreate } from "../api/client";
import type { HomeboxBulkCreateRequest } from "../api/types";

const STALE_TIME_MS = 60_000;

/** POST /api/homebox/entities/bulk. New entities change what the browse
 * page's list and location tree show, so both are invalidated on success. */
export function useBulkCreateEntities() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: HomeboxBulkCreateRequest) => postHomeboxBulkCreate(body),
    onSuccess: () => {
      for (const key of ["homebox-entities", "homebox-tree"]) {
        void queryClient.invalidateQueries({ queryKey: [key] });
      }
    },
  });
}

/** `enabled` should be the writes-enabled flag: both routes 403 otherwise. */
export function useHomeboxTags(enabled = true) {
  return useQuery({ queryKey: ["homebox-tags"], queryFn: getHomeboxTags, enabled, staleTime: STALE_TIME_MS });
}

export function useHomeboxEntityTypes(enabled = true) {
  return useQuery({ queryKey: ["homebox-entity-types"], queryFn: getHomeboxEntityTypes, enabled, staleTime: STALE_TIME_MS });
}
