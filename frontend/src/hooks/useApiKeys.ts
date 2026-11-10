import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createApiKey, listApiKeys, revokeApiKey } from "../api/client";

export const API_KEYS_QUERY_KEY = ["api-keys"] as const;

export function useApiKeysQuery() {
  return useQuery({ queryKey: API_KEYS_QUERY_KEY, queryFn: listApiKeys });
}

export function useCreateApiKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createApiKey,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: API_KEYS_QUERY_KEY }),
  });
}

export function useRevokeApiKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: revokeApiKey,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: API_KEYS_QUERY_KEY }),
  });
}
