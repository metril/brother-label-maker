import { useQuery } from "@tanstack/react-query";
import { getAuthMe } from "../api/client";

/** Shared query key -- App.tsx's global 401 handler invalidates this exact
 * key so a session that ends mid-use (logout in another tab, the IdP's own
 * id_token expiring -- see backend/api/auth_gate.py's `get_session_user`
 * re-checking `exp` on every request) flips this hook within one failed
 * request, not up to a full `staleTime` later. */
export const AUTH_ME_QUERY_KEY = ["auth-me"] as const;

const STALE_TIME_MS = 30_000;

/** GET /api/auth/me (task 4.1) -- the ONE probe AppShell needs to decide
 * whether to render the app or a sign-in panel, in EITHER auth mode: mode
 * "none" always answers a constant `{auth_mode: "none", authenticated:
 * true, user: null}` (see that route's own docstring), so this hook -- and
 * every caller of it -- never has to branch on mode ahead of time, only on
 * the response shape. */
export function useAuth() {
  return useQuery({ queryKey: AUTH_ME_QUERY_KEY, queryFn: getAuthMe, staleTime: STALE_TIME_MS });
}
