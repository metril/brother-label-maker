import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import { server } from "./msw/server";

/** Every MockWebSocket constructed during the current test, in creation
 * order -- so a test can grab the instance useJobEvents created (usually
 * `mockWebSocketInstances.at(-1)!`) and drive it directly: `.open()` to
 * simulate a successful connection, `.emit({...})` to push a server frame
 * (JSON-stringified, matching the real /api/ws contract), or just leave it
 * alone (defaults to auto-open, see below). Cleared after every test. */
export const mockWebSocketInstances: MockWebSocket[] = [];

/** jsdom's real WebSocket tries an actual network connection, which is
 * both slow and irrelevant under test -- stub it with something a test can
 * drive synchronously instead. Defaults to auto-opening (mimicking a
 * healthy connection, so unrelated tests don't churn through
 * useJobEvents's reconnect-with-backoff loop for no reason); tests that
 * care about a specific WS event call `.emit(...)` on the instance. */
export class MockWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  url: string;
  readyState: 0 | 1 | 2 | 3 = MockWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    mockWebSocketInstances.push(this);
    queueMicrotask(() => this.open());
  }

  /** Simulate the server accepting the connection. */
  open() {
    if (this.readyState !== MockWebSocket.CONNECTING) return;
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }

  /** Simulate the server pushing a JSON event frame (the real /api/ws
   * contract is always JSON: {event, job_id, error?}). */
  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }

  close() {
    if (this.readyState === MockWebSocket.CLOSED) return;
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({ code: 1000 });
  }

  send() {
    // no-op: nothing under test ever needs the client to send a frame.
  }
}

/** Every MockIntersectionObserver constructed during the current test, in
 * creation order -- a test grabs the instance IconField.tsx's windowed
 * SymbolPicker created for its sentinel div (usually
 * `mockIntersectionObserverInstances.at(-1)!`) and calls `.trigger()` on it
 * to simulate the sentinel scrolling into view. Cleared after every test. */
export const mockIntersectionObserverInstances: MockIntersectionObserver[] = [];

/** jsdom implements no IntersectionObserver at all -- stub it with
 * something a test can drive synchronously. Real observers report once per
 * observed target; this app only ever observes a single windowing sentinel
 * per picker instance, so `.trigger()` fabricates one entry per currently-
 * observed target rather than a general per-target queue/timing model.
 *
 * `root`/`rootMargin` are captured from the constructor's own `options`
 * (SymbolBrowser.tsx's windowing fix needs its own grid element as `root`,
 * not the viewport -- a test asserts that directly against this field) --
 * purely observational, though: `observe`/`unobserve`/`trigger` below don't
 * actually filter by root/threshold the way a real browser would, so
 * existing tests that never inspect these fields see no behavior change. */
export class MockIntersectionObserver implements IntersectionObserver {
  readonly root: Element | Document | null;
  readonly rootMargin: string;
  readonly scrollMargin: string = "";
  readonly thresholds: ReadonlyArray<number> = [];

  #callback: IntersectionObserverCallback;
  #targets = new Set<Element>();

  /** Every observe/unobserve/disconnect call this instance has received, in
   * call order -- `#targets` being a bare Set means `observe()`/`trigger()`
   * alone can't tell a test whether a target was re-armed (unobserve then
   * observe of the SAME node) or just left alone since mount: `observe()`
   * on an already-observed target is a silent Set.add no-op, and
   * `trigger()` fires for whatever's currently in the Set regardless of how
   * many times (or whether) it was re-observed. This log lets a test assert
   * on the CALLS themselves -- e.g. SymbolBrowser.test.tsx's re-arm
   * regression, which needs to prove an actual unobserve+observe pair
   * happened, not just that growth eventually occurred (additive: doesn't
   * change observe/unobserve/disconnect's existing Set behavior). */
  calls: Array<{ op: "observe" | "unobserve" | "disconnect"; target: Element }> = [];

  constructor(callback: IntersectionObserverCallback, options?: IntersectionObserverInit) {
    this.#callback = callback;
    this.root = options?.root ?? null;
    this.rootMargin = options?.rootMargin ?? "";
    mockIntersectionObserverInstances.push(this);
  }

  observe(target: Element) {
    this.calls.push({ op: "observe", target });
    this.#targets.add(target);
  }

  unobserve(target: Element) {
    this.calls.push({ op: "unobserve", target });
    this.#targets.delete(target);
  }

  disconnect() {
    for (const target of this.#targets) this.calls.push({ op: "disconnect", target });
    this.#targets.clear();
  }

  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }

  /** Simulate every currently-observed target crossing the visibility
   * threshold -- `isIntersecting: true` (the default) is the "sentinel
   * scrolled into view, grow the window" case a windowing test drives;
   * `false` simulates it leaving. No-op when nothing is observed yet. */
  trigger(isIntersecting = true) {
    const entries = Array.from(this.#targets).map(
      (target) => ({ target, isIntersecting, intersectionRatio: isIntersecting ? 1 : 0 }) as IntersectionObserverEntry,
    );
    if (entries.length > 0) this.#callback(entries, this);
  }
}

/** Per-query matchMedia state for the reactive stub below -- `matches`
 * defaults to `false` for any query a test hasn't opted into (see
 * setMediaQueryMatches), and `mediaQueryListeners` holds every `change`
 * listener currently registered, keyed by the query STRING rather than by
 * MediaQueryList object identity (each `window.matchMedia(query)` call
 * below returns a fresh object, so identity-keying would silently drop
 * listeners). Both cleared after every test. */
const mediaQueryState = new Map<string, boolean>();
const mediaQueryListeners = new Map<string, Set<() => void>>();

/** Flip a media query's stubbed `matches` value and notify every listener
 * currently registered for that exact query string (e.g. a hook's
 * `mql.addEventListener("change", ...)`). Call this after a hook has
 * already mounted and wrap it in `act(...)` -- same reasoning as this
 * file's MockWebSocket.emit: it synchronously drives a React state update
 * outside of React's own event handling. */
export function setMediaQueryMatches(query: string, matches: boolean): void {
  mediaQueryState.set(query, matches);
  for (const listener of mediaQueryListeners.get(query) ?? []) listener();
}

beforeAll(() => {
  // msw's own WebSocketInterceptor patches globalThis.WebSocket too (not
  // just fetch/XHR) the moment the server starts listening, and errors on
  // any connection with no `ws.link` handler -- stub AFTER listen() so our
  // MockWebSocket, not msw's interceptor, is what `new WebSocket(...)`
  // resolves to for the rest of the suite.
  server.listen({ onUnhandledRequest: "error" });
  vi.stubGlobal("WebSocket", MockWebSocket);
  vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);

  // jsdom doesn't implement matchMedia at all -- usePrefersReducedMotion
  // and useIsDesktop need SOME implementation to avoid throwing. Each call
  // returns a fresh object backed by the shared mediaQueryState/
  // mediaQueryListeners maps above, keyed by the query string: `matches` is
  // a live getter (not a snapshot) so a test's setMediaQueryMatches(...)
  // after mount is visible on every outstanding MediaQueryList for that
  // query, and addEventListener/removeEventListener register/unregister
  // real listeners instead of no-ops. Defaults to `false` (e.g. "no
  // reduced-motion preference", "not desktop-width") unless a test opts in
  // via setMediaQueryMatches.
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      get matches() {
        return mediaQueryState.get(query) ?? false;
      },
      media: query,
      onchange: null,
      addEventListener: (type: string, fn: () => void) => {
        if (type !== "change") return;
        if (!mediaQueryListeners.has(query)) mediaQueryListeners.set(query, new Set());
        mediaQueryListeners.get(query)!.add(fn);
      },
      removeEventListener: (type: string, fn: () => void) => {
        if (type !== "change") return;
        mediaQueryListeners.get(query)?.delete(fn);
      },
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
});

afterEach(() => {
  cleanup();
  server.resetHandlers();
  mockWebSocketInstances.length = 0;
  mockIntersectionObserverInstances.length = 0;
  mediaQueryState.clear();
  mediaQueryListeners.clear();
  // stores/tray.ts persists to localStorage (zustand's persist middleware),
  // and hooks/useTheme.ts persists `lm-theme` -- clear it after every test
  // so one test's tray/theme state can never leak into the next via a
  // shared jsdom localStorage, independent of whatever a test itself does
  // with useTrayStore.setState(...) or useTheme's own setTheme(...).
  localStorage.clear();
  // useTheme.ts's `applyTheme` sets/removes this attribute directly on
  // `document.documentElement` -- a real DOM node shared across every test
  // in the same jsdom environment (unlike component-local state, which
  // unmounts), so it needs its own explicit reset alongside localStorage.
  document.documentElement.removeAttribute("data-theme");
});

afterAll(() => {
  server.close();
  vi.unstubAllGlobals();
});
