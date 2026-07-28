import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { Designer } from "./pages/Designer";
import { History } from "./pages/History";
import { Presets } from "./pages/Presets";
import { JobEventsProvider } from "./hooks/useJobEvents";

/** Task 2.13: the app stops being a single screen here -- three routes
 * (Designer at "/", Presets, History), all inside the SAME AppShell (its
 * own primary nav + status bar persist across navigation) and the SAME
 * QueryClient/JobEventsProvider (one WS connection, one query cache, for
 * the whole app regardless of route). stores/designer.ts and
 * stores/tray.ts are module-level zustand stores, not component state --
 * navigating away from Designer unmounts it, but the store itself lives on
 * unchanged, so a design in progress survives a round trip through
 * Presets/History (verified live + in App.routing.test.tsx). */
function App() {
  // Created once per mount (not module scope) so each App instance -- real
  // or under test -- gets its own cache instead of leaking state/timers
  // across renders.
  const [queryClient] = useState(() => new QueryClient());

  return (
    <QueryClientProvider client={queryClient}>
      <JobEventsProvider>
        <BrowserRouter>
          <AppShell>
            <Routes>
              <Route path="/" element={<Designer />} />
              <Route path="/presets" element={<Presets />} />
              <Route path="/history" element={<History />} />
            </Routes>
          </AppShell>
        </BrowserRouter>
      </JobEventsProvider>
    </QueryClientProvider>
  );
}

export default App;
