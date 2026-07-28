import { useQuery } from "@tanstack/react-query";
import { getGallery } from "../api/client";

/** GET /api/gallery -- a fixed curated catalogue, rendered and cached
 * server-side. staleTime: Infinity for the same static-catalog reason as
 * useTapes/useFonts: the entries only change with a deploy. */
export function useGallery() {
  return useQuery({ queryKey: ["gallery"], queryFn: getGallery, staleTime: Infinity });
}
