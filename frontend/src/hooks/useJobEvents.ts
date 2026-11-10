import { createContext, createElement, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { JobEvent } from "../api/types";

export type WsConnectionState = "connecting" | "live" | "reconnecting";

const INITIAL_BACKOFF_MS = 500;
const MAX_BACKOFF_MS = 10_000;
const MAX_EVENTS = 200;

export interface UseJobEventsResult {
  connectionState: WsConnectionState;
  /** Latest event per job_id, e.g. events["abc123"]?.event === "job.done". */
  events: Record<string, JobEvent>;
}

function wsUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/api/v1/ws`;
}

/** Native WebSocket connection to /api/v1/ws with exponential backoff
 * (capped at 10s) reconnect. One event stream, fanned out by job_id so any
 * number of trackers (PrintButton instances) can read the latest event for
 * their own job without opening their own socket -- see JobEventsProvider. */
export function useJobEvents(): UseJobEventsResult {
  const [connectionState, setConnectionState] = useState<WsConnectionState>("connecting");
  const queryClient = useQueryClient();
  const [events, setEvents] = useState<Record<string, JobEvent>>({});

  useEffect(() => {
    let closedByUs = false;
    let backoffMs = INITIAL_BACKOFF_MS;
    let socket: WebSocket | null = null;
    let hasConnected = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    function connect() {
      setConnectionState((prev) => (prev === "live" ? prev : "connecting"));
      socket = new WebSocket(wsUrl());

      socket.onopen = () => {
        backoffMs = INITIAL_BACKOFF_MS;
        setConnectionState("live");
        // Events sent while disconnected are lost: refetch what they would have updated.
        if (hasConnected) {
          queryClient.invalidateQueries({ queryKey: ["print-job-poll"] });
          queryClient.invalidateQueries({ queryKey: ["history"] });
        }
        hasConnected = true;
      };

      socket.onmessage = (event: MessageEvent<string>) => {
        try {
          const data = JSON.parse(event.data) as JobEvent;
          if (typeof data.job_id === "string" && typeof data.event === "string") {
            setEvents((prev) => {
              const next = { ...prev };
              // Re-insert so the most recently updated job is last, then drop the oldest.
              delete next[data.job_id];
              next[data.job_id] = data;
              const keys = Object.keys(next);
              for (const key of keys.slice(0, Math.max(0, keys.length - MAX_EVENTS))) delete next[key];
              return next;
            });
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
  }, [queryClient]);

  return { connectionState, events };
}

// Two contexts, not one: every `job.progress` frame replaces `events`, so a
// single combined value re-rendered every consumer (AppShell, Diagnostics)
// that only ever reads `connectionState`. Split so those subscribe to the
// connection alone and only event readers re-render per frame.
const JobConnectionContext = createContext<WsConnectionState | null>(null);
const JobEventsContext = createContext<Record<string, JobEvent> | null>(null);

/** One WS connection for the whole app -- mount near the root (App.tsx) and
 * read it anywhere below via useJobEventsContext(), instead of every
 * PrintButton opening its own socket. */
export function JobEventsProvider({ children }: { children: ReactNode }) {
  const { connectionState, events } = useJobEvents();
  return createElement(
    JobConnectionContext.Provider,
    { value: connectionState },
    createElement(JobEventsContext.Provider, { value: events }, children),
  );
}

/** Connection state only -- does NOT re-render on job events (prefer this
 * over useJobEventsContext() when `events` isn't needed). */
export function useJobConnectionState(): WsConnectionState {
  const ctx = useContext(JobConnectionContext);
  if (!ctx) {
    throw new Error("useJobConnectionState must be used within a JobEventsProvider");
  }
  return ctx;
}

function useJobEventsMap(): Record<string, JobEvent> {
  const ctx = useContext(JobEventsContext);
  if (!ctx) {
    throw new Error("useJobEventsContext must be used within a JobEventsProvider");
  }
  return ctx;
}

export function useJobEventsContext(): UseJobEventsResult {
  const connectionState = useJobConnectionState();
  const events = useJobEventsMap();
  return useMemo(() => ({ connectionState, events }), [connectionState, events]);
}

/** Convenience: the latest event for one job id, memoized so consumers don't
 * re-render on unrelated job events. */
export function useJobEvent(jobId: string | null): JobEvent | undefined {
  const events = useJobEventsMap();
  return useMemo(() => (jobId ? events[jobId] : undefined), [events, jobId]);
}
