import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import { server } from "./msw/server";

/** jsdom's real WebSocket tries an actual network connection (and fails
 * async, which is harmless but slow and noisy) -- stub it with one that
 * closes itself on the next microtask, so useJobEvents's reconnect-with-
 * backoff path runs deterministically without ever touching the network. */
class MockWebSocket {
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
    queueMicrotask(() => {
      this.readyState = MockWebSocket.CLOSED;
      this.onclose?.({ code: 1006 });
    });
  }

  close() {
    this.readyState = MockWebSocket.CLOSED;
  }

  send() {
    // no-op: nothing under test ever needs the client to send a frame.
  }
}

beforeAll(() => {
  vi.stubGlobal("WebSocket", MockWebSocket);
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  cleanup();
  server.resetHandlers();
});

afterAll(() => {
  server.close();
  vi.unstubAllGlobals();
});
