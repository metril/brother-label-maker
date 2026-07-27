import { useQuery } from "@tanstack/react-query";
import { getFonts } from "../api/client";

/** GET /api/fonts -- the bundled font catalog (backend/render/fonts.py's
 * list_fonts()). staleTime: Infinity because this is a static, versioned-
 * with-the-backend catalog, not something that changes during a session --
 * no point refetching it. */
export function useFonts() {
  return useQuery({ queryKey: ["fonts"], queryFn: getFonts, staleTime: Infinity });
}
