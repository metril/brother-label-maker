import { useState } from "react";
import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { ApiError } from "./api/client";
import { AppShell } from "./components/AppShell";
import { Designer } from "./pages/Designer";
import { Gallery } from "./pages/Gallery";
import { History } from "./pages/History";
import { Homebox } from "./pages/Homebox";
import { Presets } from "./pages/Presets";
import { AUTH_ME_QUERY_KEY } from "./hooks/useAuth";
import { JobEventsProvider } from "./hooks/useJobEvents";

/** Task 2.13: the app stops being a single screen here -- Designer at "/",
 * Presets, History, Gallery, and (task 3.4) Homebox, all inside the SAME
 * AppShell (its own primary nav + status bar persist across navigation) and
 * the SAME QueryClient/JobEventsProvider (one WS connection, one query
 * cache, for the whole app regardless of route). stores/designer.ts and
 * stores/tray.ts are module-level zustand stores, not component state --
 * navigating away from Designer unmounts it, but the store itself lives on
 * unchanged, so a design in progress survives a round trip through
 * Presets/History (verified live + in App.routing.test.tsx). */
function App() {
  // Created once per mount (not module scope) so each App instance -- real
  // or under test -- gets its own cache instead of leaking state/timers
  // across renders.
  const [queryClient] = useState(
    () =>
      new QueryClient({
        queryCache: new QueryCache({
          // task 4.1: a session that ends mid-use (signed out in another
          // tab, or the IdP's own id_token expiring -- see backend/api/
          // auth_gate.py's `get_session_user`, re-checked on every
          // request) surfaces as a 401 on whatever OTHER query happened to
          // be in flight at the time. Re-fetching /auth/me right away
          // (instead of waiting up to its own staleTime) is what makes
          // AppShell's sign-in panel reappear promptly. `auth-me` itself
          // never actually 401s (see router_auth.py's `/auth/me` -- always
          // 200 in both modes), so the query-key check below is a
          // defensive guard against a future change turning this into a
          // refetch loop, not something this code path is expected to hit.
          onError: (error, query) => {
            if (
              error instanceof ApiError &&
              error.status === 401 &&
              query.queryKey[0] !== AUTH_ME_QUERY_KEY[0]
            ) {
              void queryClient.invalidateQueries({ queryKey: AUTH_ME_QUERY_KEY });
            }
          },
        }),
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <JobEventsProvider>
        <BrowserRouter>
          <AppShell>
            <Routes>
              <Route path="/" element={<Designer />} />
              <Route path="/presets" element={<Presets />} />
              <Route path="/history" element={<History />} />
              <Route path="/gallery" element={<Gallery />} />
              <Route path="/homebox" element={<Homebox />} />
            </Routes>
          </AppShell>
        </BrowserRouter>
      </JobEventsProvider>
    </QueryClientProvider>
  );
}

export default App;
