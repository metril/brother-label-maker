import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ApiError, postPrinterCut } from "../api/client";

// Item 3 (fix wave): the POST itself settles in milliseconds (it only
// queues a job, same as every other print-job create) -- `isPending` alone
// is disabled for that window only, leaving a wide-open gap where a second
// click queues a SECOND physical cut before the first click's request has
// even round-tripped. Held disabled for this long after a successful 202
// instead -- comfortably longer than any plausible double-click, short
// enough not to feel broken for a deliberate second press a few seconds
// later.
const COOLDOWN_MS = 2500;

export interface UseFeedCutResult {
  feedCut: () => void;
  isPending: boolean;
  /** `isPending` OR still inside the post-success cooldown (see
   * COOLDOWN_MS) -- both buttons this hook backs (TrayPanel.tsx,
   * Diagnostics.tsx) drive their `disabled` off THIS, not `isPending`
   * alone, so the button stays disabled through the cooldown too. */
  isBusy: boolean;
  /** A transient inline message from the last failed attempt -- cleared the
   * moment `feedCut()` is called again (mirrors usePrintJob's own
   * `cancelError`, minus that hook's extra "also clear on terminal state"
   * rule, since a feed-and-cut request has no terminal state of its own to
   * wait for here -- see this hook's own docstring). */
  error: string | null;
}

/** Feed & cut (design doc: docs/superpowers/specs/2026-08-04-feed-cut-
 * trigger-design.md): what the button this backs actually does to the
 * machine. The P-touch raster protocol has no standalone "cut" opcode -- a
 * cut only ever happens at end-of-page (`FF`/`CTRL_Z`) with the auto-cut bit
 * set, and the cutter sits ~24.5mm downstream of the print head
 * (`MIN_FEED_MM`, backend/driver/geometry.py), so every cut inherently
 * advances that ~25mm first. There is no "cut without feed": releasing a
 * chained job's printed tape past the blade produces exactly this same
 * advance (the user's own printed content clearing the cutter, not waste);
 * triggering it with nothing pending instead produces a blank ~25mm
 * snippet. This hook wraps POST /api/printer/cut, which queues that as a
 * REAL job (`kind: "feed_cut"`) rather than firing a synchronous printer
 * command -- it serializes against any in-flight print via the same single
 * worker + USB lock a print job does, and shows up in History same as one.
 *
 * Mirrors hooks/usePrintJob.ts's own `cancelMutation` shape (transient
 * inline `error`, `isPending`) rather than that hook's full submit/poll/WS
 * lifecycle: callers (TrayPanel's compact action-row button, Diagnostics'
 * Printer panel) only need to know "is the request in flight" / "did
 * QUEUING it fail" -- the queued job's own progress-to-completion is
 * already visible via the existing WS-driven History/Diagnostics views,
 * with no useful terminal-state UI of its own to add at the call site. */
export function useFeedCut(): UseFeedCutResult {
  const [error, setError] = useState<string | null>(null);
  const [inCooldown, setInCooldown] = useState(false);
  // A plain ref (not query-client/WS-tracked -- deliberate, see COOLDOWN_MS's
  // own comment: this hook stays dependency-free rather than gaining a WS
  // subscription just to know when the job.done for THIS click's job
  // arrives) so the timeout can be cleared on unmount without leaking a
  // setState call into an unmounted component.
  const cooldownTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (cooldownTimeout.current !== null) {
        clearTimeout(cooldownTimeout.current);
      }
    };
  }, []);

  const mutation = useMutation({
    mutationFn: () => postPrinterCut(),
    onSuccess: () => {
      setError(null);
      setInCooldown(true);
      cooldownTimeout.current = setTimeout(() => {
        setInCooldown(false);
        cooldownTimeout.current = null;
      }, COOLDOWN_MS);
    },
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : "feed & cut request failed");
    },
  });

  function feedCut() {
    if (mutation.isPending || inCooldown) return;
    setError(null);
    mutation.mutate();
  }

  return {
    feedCut,
    isPending: mutation.isPending,
    isBusy: mutation.isPending || inCooldown,
    error,
  };
}
