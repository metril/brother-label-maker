import { createContext, createElement, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { JobEvent } from "../api/types";

export type WsConnectionState = "connecting" | "live" | "reconnecting";

const INITIAL_BACKOFF_MS = 500;
const MAX_BACKOFF_MS = 10_000;

export interface UseJobEventsResult {
  connectionState: WsConnectionState;
  /** Latest event per job_id, e.g. events["abc123"]?.event === "job.done". */
  events: Record<string, JobEvent>;
}

function wsUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/api/ws`;
}

/** Native WebSocket connection to /api/ws with exponential backoff
 * (capped at 10s) reconnect. One event stream, fanned out by job_id so any
 * number of trackers (PrintButton instances) can read the latest event for
 * their own job without opening their own socket -- see JobEventsProvider. */
export function useJobEvents(): UseJobEventsResult {
  const [connectionState, setConnectionState] = useState<WsConnectionState>("connecting");
  const [events, setEvents] = useState<Record<string, JobEvent>>({});

  useEffect(() => {
    let closedByUs = false;
    let backoffMs = INITIAL_BACKOFF_MS;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    function connect() {
      setConnectionState((prev) => (prev === "live" ? prev : "connecting"));
      socket = new WebSocket(wsUrl());

      socket.onopen = () => {
        backoffMs = INITIAL_BACKOFF_MS;
        setConnectionState("live");
      };

      socket.onmessage = (event: MessageEvent<string>) => {
        try {
          const data = JSON.parse(event.data) as JobEvent;
          if (typeof data.job_id === "string" && typeof data.event === "string") {
            setEvents((prev) => ({ ...prev, [data.job_id]: data }));
          }
        } catch {
          // ignore malformed frames
        }
      };

      socket.onerror = () => {
        socket?.close();
      };

      socket.onclose = () => {
        if (closedByUs) return;
        setConnectionState("reconnecting");
        const delay = backoffMs;
        backoffMs = Math.min(backoffMs * 2, MAX_BACKOFF_MS);
        reconnectTimer = setTimeout(connect, delay);
      };
    }

    connect();

    return () => {
      closedByUs = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, []);

  return { connectionState, events };
}

const JobEventsContext = createContext<UseJobEventsResult | null>(null);

/** One WS connection for the whole app -- mount near the root (App.tsx) and
 * read it anywhere below via useJobEventsContext(), instead of every
 * PrintButton opening its own socket. */
export function JobEventsProvider({ children }: { children: ReactNode }) {
  const value = useJobEvents();
  return createElement(JobEventsContext.Provider, { value }, children);
}

export function useJobEventsContext(): UseJobEventsResult {
  const ctx = useContext(JobEventsContext);
  if (!ctx) {
    throw new Error("useJobEventsContext must be used within a JobEventsProvider");
  }
  return ctx;
}

/** Convenience: the latest event for one job id, memoized so consumers don't
 * re-render on unrelated job events. */
export function useJobEvent(jobId: string | null): JobEvent | undefined {
  const { events } = useJobEventsContext();
  return useMemo(() => (jobId ? events[jobId] : undefined), [events, jobId]);
}
