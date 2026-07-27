import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppShell } from "./components/AppShell";
import { Designer } from "./pages/Designer";
import { JobEventsProvider } from "./hooks/useJobEvents";

function App() {
  // Created once per mount (not module scope) so each App instance -- real
  // or under test -- gets its own cache instead of leaking state/timers
  // across renders.
  const [queryClient] = useState(() => new QueryClient());

  return (
    <QueryClientProvider client={queryClient}>
      <JobEventsProvider>
        <AppShell>
          <Designer />
        </AppShell>
      </JobEventsProvider>
    </QueryClientProvider>
  );
}

export default App;
