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

beforeAll(() => {
  // msw's own WebSocketInterceptor patches globalThis.WebSocket too (not
  // just fetch/XHR) the moment the server starts listening, and errors on
  // any connection with no `ws.link` handler -- stub AFTER listen() so our
  // MockWebSocket, not msw's interceptor, is what `new WebSocket(...)`
  // resolves to for the rest of the suite.
  server.listen({ onUnhandledRequest: "error" });
  vi.stubGlobal("WebSocket", MockWebSocket);
});

afterEach(() => {
  cleanup();
  server.resetHandlers();
  mockWebSocketInstances.length = 0;
});

afterAll(() => {
  server.close();
  vi.unstubAllGlobals();
});
