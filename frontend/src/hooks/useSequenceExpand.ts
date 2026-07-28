import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ApiError, postExpand } from "../api/client";
import { firstTextFieldValue, validateSequence, type SequenceFieldErrors } from "../lib/sequence";
import { useDesignerStore } from "../stores/designer";
import { useLabelTypes } from "./useLabelTypes";
import type { ExpandResponse, Sequence } from "../api/types";

const DEBOUNCE_MS = 300;
/** Matches expand_tokens' own two token shapes (backend/render/serialize.
 * py) -- used only to decide whether the current "first text field" value
 * is worth sending as `sample` at all (see the docstring below). */
const TOKEN_RE = /\{seq\}|\{csv\./;

export interface UseSequenceExpandResult {
  /** The last successful POST /api/render/expand response for the
   * CURRENT (enabled, client-valid) sequence -- null while serialization
   * is off, the sequence has a client-side field error, or no request has
   * resolved yet. */
  data: ExpandResponse | null;
  /** The "first text field"'s raw current value (schema/params-order --
   * see lib/sequence.ts's firstTextFieldValue), regardless of whether it
   * contains a token -- SequenceEditor's live-chips section uses this to
   * decide whether to show `data.samples` (token-substituted) or fall
   * back to `data.values` (raw distinct values). */
  sample: string;
  sampleHasToken: boolean;
  /** Instant, non-debounced per-field bounds errors (lib/sequence.ts's
   * validateSequence) -- shown inline immediately, and what gates the
   * network request below (a field the UI is already flagging as invalid
   * is never also sent in a request the backend would 422 on, same
   * "client-validity gating" convention as schema/numberValidity.ts). */
  fieldErrors: SequenceFieldErrors;
  isFetching: boolean;
  /** A readable message from the last FAILED request (e.g. the 1000-label
   * total-cap message, or an ALPHA run stepping past 'ZZZ') -- these are
   * cross-field checks this hook deliberately does NOT replicate
   * client-side (see validateSequence's own docstring), so the server's
   * own 422 is the source of truth for them. Always null while `data` is
   * set, while serialization is off, or while a field error already
   * blocks the request from firing at all. */
  error: string | null;
}

interface DebouncedExpandInput {
  sequence: Sequence;
  sample: string | undefined;
}

/** task 2.11: the Serialize panel's live value chips and the rest of the
 * designer's serialization-aware pieces (the feed deck's preview-index
 * stepper, the Job Tray/Print button's "Print N labels") all need the
 * SAME answer to "is the current sequence actually printable, and what
 * does it expand to" -- this hook reads everything it needs (serialization
 * enabled/sequence, the active label type's schema+params) straight from
 * the designer store/useLabelTypes rather than taking any props, so every
 * caller (components/SequenceEditor.tsx, pages/Designer.tsx) shares the
 * exact same debounced react-query cache entry (same computed queryKey)
 * instead of each firing its own redundant request. */
export function useSequenceExpand(): UseSequenceExpandResult {
  const enabled = useDesignerStore((s) => s.serializationEnabled);
  const sequence = useDesignerStore((s) => s.sequence);
  const selectedType = useDesignerStore((s) => s.selectedType);
  const paramsByType = useDesignerStore((s) => s.paramsByType);
  const { data: labelTypes } = useLabelTypes();

  const typeInfo = labelTypes?.find((t) => t.type === selectedType) ?? null;
  const params = (selectedType && paramsByType[selectedType]) || {};
  const rawSample = typeInfo ? firstTextFieldValue(typeInfo.params_schema, params) : "";
  const sampleHasToken = TOKEN_RE.test(rawSample);
  // Only send `sample` when it actually carries a token -- otherwise every
  // distinct value would expand to the SAME unchanged text (no `{seq}`/
  // `{csv.*}` to substitute), which is a useless "identical chips" demo;
  // omitting `sample` entirely instead falls back to the real distinct
  // values themselves (see SequenceEditor.tsx's chip source logic).
  const sample = sampleHasToken ? rawSample : undefined;

  // Instant, non-debounced -- for inline field errors ONLY (shown as the
  // user types, no network round-trip involved).
  const fieldErrors = validateSequence(sequence);

  const [debounced, setDebounced] = useState<DebouncedExpandInput | undefined>(undefined);

  useEffect(() => {
    const handle = setTimeout(() => setDebounced({ sequence, sample }), DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(sequence), sample]);

  // Same "clear immediately on a context switch, don't wait out the
  // debounce" fix usePreview.ts applies to a label-TYPE switch, scoped
  // here to `sequence.kind` -- otherwise switching from Numbers to List
  // would keep showing the numeric run's own last chips/total under the
  // List controls for up to one debounce window.
  const lastKindRef = useRef<string | undefined>(undefined);
  useLayoutEffect(() => {
    if (lastKindRef.current !== undefined && lastKindRef.current !== sequence.kind) {
      setDebounced(undefined);
    }
    lastKindRef.current = sequence.kind;
  }, [sequence.kind]);

  const debouncedKind = debounced?.sequence.kind ?? null;
  // I2 (usePreview.ts's own naming for this exact bug class): gate the
  // QUERY strictly on the DEBOUNCED value's validity, never the live
  // `sequence` passed in on every keystroke. Gating on the live value is
  // wrong the same way it was wrong there: it can go valid (e.g. a CSV
  // upload just populated `rows`) an instant before `debounced` has caught
  // up (still whatever settled 300ms ago -- possibly still the pre-upload
  // empty-rows sequence) -- firing a request against that stale, invalid
  // `debounced` and 422-ing for one query cycle. Confirmed live (a real
  // 422 during this task's own chrome-devtools check) before this fix.
  const debouncedFieldsOk = debounced !== undefined && Object.keys(validateSequence(debounced.sequence)).length === 0;
  const requestEnabled = enabled && debouncedFieldsOk;

  const query = useQuery({
    queryKey: ["sequence-expand", debouncedKind, debounced ? JSON.stringify(debounced) : null],
    queryFn: () => postExpand({ serialization: debounced!.sequence, sample: debounced!.sample }),
    enabled: requestEnabled,
    placeholderData: (previousData, previousQuery) =>
      debouncedKind !== null && previousQuery?.queryKey?.[1] === debouncedKind ? previousData : undefined,
    retry: false,
    staleTime: Infinity,
  });

  const error =
    requestEnabled && query.error
      ? query.error instanceof ApiError
        ? query.error.message
        : "serialization preview request failed"
      : null;

  return {
    data: requestEnabled ? (query.data ?? null) : null,
    sample: rawSample,
    sampleHasToken,
    fieldErrors,
    isFetching: query.isFetching,
    error,
  };
}
