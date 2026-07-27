import { useQuery } from "@tanstack/react-query";
import { getSymbols } from "../api/client";

/** GET /api/symbols -- the 60-icon curated Material Symbols catalog
 * (task 2.7) the "text" type's symbol picker searches. staleTime: Infinity,
 * same convention as useFonts/useTapes/useLabelTypes. */
export function useSymbols() {
  return useQuery({ queryKey: ["symbols"], queryFn: getSymbols, staleTime: Infinity });
}
