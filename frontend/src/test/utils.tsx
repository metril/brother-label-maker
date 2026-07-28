import type { ReactElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { JobEventsProvider } from "../hooks/useJobEvents";

export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

interface RenderOptions {
  /** Initial route for the MemoryRouter both helpers wrap every render in
   * (task 2.13) -- any component under test may now sit behind a `Link`/
   * `useNavigate`/`NavLink` (Presets' "Load into designer", the Designer's
   * own "View in Presets" success link, ...), which throws without a
   * Router ancestor. Defaults to "/", matching the app's own root route. */
  route?: string;
}

// Task 4.3: opt into the same React Router v7 future flags App.tsx's
// BrowserRouter now sets (v7_startTransition, v7_relativeSplatPath) --
// otherwise every test render logs the "React Router will begin wrapping
// state updates..." / "relative route resolution" console warnings the
// real app no longer does, and a MemoryRouter with different defaults than
// production's BrowserRouter would be testing subtly different navigation
// behavior than what ships.
const ROUTER_FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true } as const;

export function renderWithQueryClient(ui: ReactElement, options: RenderOptions = {}) {
  const queryClient = createTestQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[options.route ?? "/"]} future={ROUTER_FUTURE}>
        {ui}
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** For components (PrintButton, AppShell, Presets, History) that read
 * useJobEventsContext() and/or routing hooks. */
export function renderWithProviders(ui: ReactElement, options: RenderOptions = {}) {
  const queryClient = createTestQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <JobEventsProvider>
        <MemoryRouter initialEntries={[options.route ?? "/"]} future={ROUTER_FUTURE}>
          {ui}
        </MemoryRouter>
      </JobEventsProvider>
    </QueryClientProvider>,
  );
}
