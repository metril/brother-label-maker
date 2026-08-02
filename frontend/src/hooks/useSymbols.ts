import { useQuery } from "@tanstack/react-query";
import { getSymbols } from "../api/client";

/** GET /api/symbols -- the ~858-icon curated catalog (task 2.7's original
 * 60 plus commit 7's Material/Phosphor expansion) the "text" type's symbol
 * picker searches. staleTime: Infinity, same convention as
 * useFonts/useTapes/useLabelTypes. */
export function useSymbols() {
  return useQuery({ queryKey: ["symbols"], queryFn: getSymbols, staleTime: Infinity });
}
