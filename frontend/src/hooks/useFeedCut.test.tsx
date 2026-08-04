import { describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { http, HttpResponse } from "msw";
import { useFeedCut } from "./useFeedCut";
import { server } from "../test/msw/server";

function createWrapper() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe("useFeedCut", () => {
  it("feedCut() POSTs /api/printer/cut and leaves error null on success", async () => {
    let calls = 0;
    server.use(
      http.post("/api/printer/cut", () => {
        calls += 1;
        return HttpResponse.json({ job_id: "cut-job-1" }, { status: 202 });
      }),
    );

    const { result } = renderHook(() => useFeedCut(), { wrapper: createWrapper() });
    expect(result.current.error).toBeNull();
    expect(result.current.isPending).toBe(false);

    act(() => result.current.feedCut());

    await waitFor(() => expect(calls).toBe(1));
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(result.current.error).toBeNull();
  });

  it("surfaces the server's error message inline on failure", async () => {
    server.use(
      http.post("/api/printer/cut", () => HttpResponse.json({ detail: "cannot queue: printer busy" }, { status: 409 })),
    );

    const { result } = renderHook(() => useFeedCut(), { wrapper: createWrapper() });
    act(() => result.current.feedCut());

    await waitFor(() => expect(result.current.error).toBe("cannot queue: printer busy"));
    expect(result.current.isPending).toBe(false);
  });

  // Item 3 (fix wave): a double-click queues N physical cut jobs -- the
  // POST itself settles in milliseconds, so `isPending` alone leaves a
  // wide-open window for a second click to queue a second cut. `isBusy`
  // must stay true through a cooldown after a successful 202, and a second
  // feedCut() call during that window must be a no-op (no second POST).
  // Fake timers per usePreview.test.tsx's own convention (this repo's only
  // other setTimeout/debounce-driven hook).
  it("stays busy through a cooldown after a successful cut, then re-enables -- a second feedCut() during the cooldown is a no-op", async () => {
    let calls = 0;
    server.use(
      http.post("/api/printer/cut", () => {
        calls += 1;
        return HttpResponse.json({ job_id: "cut-job-cooldown" }, { status: 202 });
      }),
    );

    vi.useFakeTimers();
    try {
      const { result } = renderHook(() => useFeedCut(), { wrapper: createWrapper() });
      expect(result.current.isBusy).toBe(false);

      await act(async () => {
        result.current.feedCut();
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(calls).toBe(1);
      // The request has settled (isPending false) but the cooldown just
      // started -- still busy, unlike the pre-fix `isPending`-only gate.
      expect(result.current.isPending).toBe(false);
      expect(result.current.isBusy).toBe(true);

      // A click during the cooldown must not fire a second POST.
      act(() => result.current.feedCut());
      expect(calls).toBe(1);

      // Just under the cooldown: still busy.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2499);
      });
      expect(result.current.isBusy).toBe(true);

      // Cooldown elapses: re-enabled.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1);
      });
      expect(result.current.isBusy).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not stay busy after a FAILED request -- the cooldown only follows a successful 202", async () => {
    server.use(
      http.post("/api/printer/cut", () => HttpResponse.json({ detail: "printer busy" }, { status: 409 })),
    );

    const { result } = renderHook(() => useFeedCut(), { wrapper: createWrapper() });
    act(() => result.current.feedCut());

    await waitFor(() => expect(result.current.error).toBe("printer busy"));
    expect(result.current.isBusy).toBe(false);
  });

  // Mirrors usePrintJob's own cancelError contract: a transient message
  // that's cleared the moment the user retries, not left to linger
  // indefinitely across an unrelated later attempt.
  it("a retry (calling feedCut() again) clears the previous error immediately, without waiting for the new request to settle", async () => {
    let shouldFail = true;
    server.use(
      http.post("/api/printer/cut", () =>
        shouldFail
          ? HttpResponse.json({ detail: "cannot queue: printer busy" }, { status: 409 })
          : HttpResponse.json({ job_id: "cut-job-2" }, { status: 202 }),
      ),
    );

    const { result } = renderHook(() => useFeedCut(), { wrapper: createWrapper() });
    act(() => result.current.feedCut());
    await waitFor(() => expect(result.current.error).toBe("cannot queue: printer busy"));

    shouldFail = false;
    act(() => result.current.feedCut());
    // Cleared synchronously by feedCut() itself, before the retry's
    // response has had any chance to arrive.
    expect(result.current.error).toBeNull();

    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(result.current.error).toBeNull();
  });
});
