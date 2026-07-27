import { useQuery } from "@tanstack/react-query";
import { getTapes } from "../api/client";

/** GET /api/tapes -- the full tape geometry catalog (backend/driver/
 * geometry.py's all_tapes(), TZe + HSe). staleTime: Infinity for the same
 * reason as useFonts: a static catalog, not per-session state. */
export function useTapes() {
  return useQuery({ queryKey: ["tapes"], queryFn: getTapes, staleTime: Infinity });
}
