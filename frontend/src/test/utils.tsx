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

export function renderWithQueryClient(ui: ReactElement, options: RenderOptions = {}) {
  const queryClient = createTestQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[options.route ?? "/"]}>{ui}</MemoryRouter>
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
        <MemoryRouter initialEntries={[options.route ?? "/"]}>{ui}</MemoryRouter>
      </JobEventsProvider>
    </QueryClientProvider>,
  );
}
