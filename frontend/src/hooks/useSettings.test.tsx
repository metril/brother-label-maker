import { describe, expect, it } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useUpdateSettings } from "./useSettings";

function setup() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  for (const key of ["homebox-status", "homebox-tree", "homebox-entities", "other"]) {
    queryClient.setQueryData([key], {});
  }
  return { queryClient, ...renderHook(() => useUpdateSettings(), { wrapper }) };
}

describe("useUpdateSettings", () => {
  it("invalidates the HomeBox queries when a homebox_* key is updated", async () => {
    const { queryClient, result } = setup();
    act(() => result.current.mutate({ homebox_url: "http://hb.local" }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    for (const key of ["homebox-status", "homebox-tree", "homebox-entities"]) {
      expect(queryClient.getQueryState([key])?.isInvalidated).toBe(true);
    }
    expect(queryClient.getQueryState(["other"])?.isInvalidated).toBe(false);
  });

  it("leaves the HomeBox queries alone for unrelated keys", async () => {
    const { queryClient, result } = setup();
    act(() => result.current.mutate({ print_timeout_s: 10 }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(queryClient.getQueryState(["homebox-status"])?.isInvalidated).toBe(false);
  });
});
