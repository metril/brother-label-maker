import { create } from "zustand";
import type { LabelDefinition, Sequence } from "../api/types";

/** The "current, unsaved design" half of what the tray can print -- built by
 * pages/Designer.tsx (which owns the schema/params/preview this is derived
 * from) and handed down as one bundle rather than half a dozen loose props.
 * `null` away from the Designer page -- there is no such design to fall
 * back to or add from on any other route, see TrayPanelProps' own doc
 * (components/TrayPanel.tsx). */
export interface CurrentDesign {
  definition: LabelDefinition;
  /** Strict "safe to submit THIS right now" gate -- content present, every
   * number field in bounds, and (if serialization is on) the run confirmed
   * printable. Mirrors what Designer.tsx used to compute as its own
   * `jobTrayCanSubmit` pre-2.12. */
  canSubmit: boolean;
  /** The debounce-safe predicate (schema/renderable.ts + numberValidity.ts)
   * applied to a single definition -- used to gate usePrintEstimate's
   * network call the same "match the debounced value, not the live one"
   * way usePreview.ts already does (see that hook's own docstring). */
  isRenderable: (definition: LabelDefinition) => boolean;
  png: string | null;
  lengthMm: number | null;
  /** "Type + first text line" -- what a tray item added FROM this design
   * would be captioned (lib/tray.ts's describeCurrentDesign). */
  label: string;
  serializationEnabled: boolean;
  /** The confirmed serialization spec, or null (off, or not yet confirmed
   * printable) -- see Designer.tsx's own `activeSerialization`. */
  serialization: Sequence | null;
  totalLabels: number | null;
  /** True while the Serialize panel (components/SequenceEditor.tsx) is
   * ALREADY showing its own error for the current settled sequence (e.g. a
   * total-labels-over-1000 422) -- carry-forward fix: lets the tray's
   * estimate panel defer to that instead of re-printing the identical raw
   * server message a second time (see the estimate-error branch below). */
  serializationHasVisibleError: boolean;
}

interface CurrentDesignState {
  current: CurrentDesign | null;
  setCurrent: (design: CurrentDesign | null) => void;
}

/** The Designer route's own "current, unsaved design", lifted out of
 * components/JobTray.tsx (retired) into a store so it can be read from
 * outside Designer's own subtree: written ONLY by pages/Designer.tsx's own
 * mirror effect (CurrentDesignMirrorEffect), cleared on unmount (there IS no
 * current design once you navigate away). Not persisted -- same "pure
 * transient UI state" category as stores/chainPreview.ts's own `open`; a
 * reload has no business resurrecting a half-typed design that was never
 * added to the tray or saved as a preset.
 *
 * Two consumers:
 *  - components/GlobalTrayDrawer.tsx: now the ONE tray surface for every
 *    route, including "/" -- this is what powers its "current design" tray
 *    affordances (the empty-tray-prints-the-current-design fallback, "+ Add
 *    to tray") specifically on the Design route, exactly the way
 *    components/JobTray.tsx used to via a prop.
 *  - components/ChainPreviewDrawer.tsx: its own empty-tray fallback (a
 *    strict subset of these fields -- definition/serialization/canSubmit). */
export const useCurrentDesignStore = create<CurrentDesignState>((set) => ({
  current: null,
  setCurrent: (current) => set({ current }),
}));
