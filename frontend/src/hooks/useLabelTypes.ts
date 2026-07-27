import { useQuery } from "@tanstack/react-query";
import { getLabelTypes } from "../api/client";

/** GET /api/label-types -- the 9-type catalog (type/title/category/
 * min_tape_mm/params_schema) the left rail and the schema-driven form
 * engine are both built from. staleTime: Infinity, same convention as
 * useFonts/useTapes: a static, versioned-with-the-backend catalog. */
export function useLabelTypes() {
  return useQuery({ queryKey: ["label-types"], queryFn: getLabelTypes, staleTime: Infinity });
}
