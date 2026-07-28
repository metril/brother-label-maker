import { useQuery } from "@tanstack/react-query";
import { getHomeboxSettings } from "../api/client";

export const HOMEBOX_SETTINGS_QUERY_KEY = ["homebox-settings"] as const;

/** GET /api/homebox/settings as a live query (task 4.2's Settings page --
 * the "editable qr_base_url setting" section). pages/Homebox.tsx reads the
 * same endpoint too, but as a one-off call inside its own "add to tray"
 * mutation (it just needs the CURRENT value at click time); this hook is
 * for a page that displays and edits the setting itself, so it needs to
 * refetch after a save (see pages/Settings.tsx's mutation onSuccess). */
export function useHomeboxSettingsQuery() {
  return useQuery({ queryKey: HOMEBOX_SETTINGS_QUERY_KEY, queryFn: getHomeboxSettings });
}
