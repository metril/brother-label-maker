import { useQuery } from "@tanstack/react-query";
import { getPresets } from "../api/client";

interface UsePresetsParams {
  labelType?: string;
  q?: string;
}

/** GET /api/presets (task 2.13), filtered by `label_type`/`q` -- the
 * Presets page's own search box + type filter drive these straight through
 * as query params (see api/router_presets.py's list_presets). */
export function usePresets({ labelType, q }: UsePresetsParams) {
  return useQuery({
    queryKey: ["presets", labelType ?? null, q ?? null],
    queryFn: () => getPresets({ label_type: labelType, q }),
  });
}
