import type { RefObject } from "react";
import { csvColumns } from "../../lib/sequence";
import { useDesignerStore } from "../../stores/designer";

interface TokenInsertButtonsProps {
  /** The underlying <input> this row's tokens insert into -- see ui/
   * inputs.tsx's TextInput forwardRef. */
  inputRef: RefObject<HTMLInputElement | null>;
  value: string;
  onChange: (value: string) => void;
  /** Already-qualified field label (e.g. "Lines 2") -- purely for each
   * button's own aria-label, not shown. */
  fieldLabel: string;
}

/** task 2.11 brief: "a small 'Insert {seq}' affordance next to text inputs
 * when serialization is on (and {csv.col} chips in CSV mode) -- clicking
 * inserts at the cursor." Reads serializationEnabled/sequence straight
 * from the designer store (a cross-cutting concern, not threaded as a new
 * prop through SchemaForm -> SchemaField -> ArrayOfStrings' own
 * signatures) so every text-capable field gets this for free without the
 * generic form engine's prop contracts changing at all -- "do NOT
 * restructure the form controls" from the brief. Renders nothing while
 * serialization is off: the form looks and behaves exactly as it did
 * before this task for the common (non-serialized) case. */
export function TokenInsertButtons({ inputRef, value, onChange, fieldLabel }: TokenInsertButtonsProps) {
  const enabled = useDesignerStore((s) => s.serializationEnabled);
  const sequence = useDesignerStore((s) => s.sequence);

  if (!enabled) return null;

  const tokens =
    sequence.kind === "csv"
      ? ["{seq}", ...csvColumns(sequence.rows ?? []).map((column) => `{csv.${column}}`)]
      : ["{seq}"];

  function insertToken(token: string) {
    const el = inputRef.current;
    const start = el?.selectionStart ?? value.length;
    const end = el?.selectionEnd ?? value.length;
    const next = value.slice(0, start) + token + value.slice(end);
    onChange(next);
    const caret = start + token.length;
    // Re-focus and place the caret AFTER the inserted token, next frame --
    // `onChange` above re-renders the controlled input with the new value
    // first; setting selection synchronously in the same tick can land on
    // the pre-update DOM value in some browsers.
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(caret, caret);
    });
  }

  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {tokens.map((token) => (
        <button
          key={token}
          type="button"
          aria-label={`Insert ${token} into ${fieldLabel}`}
          onClick={() => insertToken(token)}
          className="rounded border border-deck-600 bg-deck-800 px-1.5 py-0.5 font-mono text-[10px] text-deck-400 hover:border-amber-500 hover:text-amber-300"
        >
          + {token}
        </button>
      ))}
    </div>
  );
}
