// Plain-language descriptions per the design doc's copy voice ("what the
// user gets, not protocol jargon"). chain_ff/strip_marks' underlying tape
// math is UNVERIFIED until the physical checkpoint (see backend/render/
// estimate.py's own module docstring) -- that caveat stays in code
// comments only, never in this user-facing copy.
//
// Lives in lib/ (not TrayPanel.tsx, where this was originally defined) so
// ChainedPreviewDialog's own mode tabs can reuse the SAME copy rather than
// a second, driftable copy of it, without a component-to-component import
// -- TrayPanel.tsx renders ChainedPreviewDialog itself, so re-exporting
// this from TrayPanel.tsx would have made the two files circularly
// dependent (and tripped react-refresh/only-export-components, which
// requires a component file to export components only).
import type { ChainMode } from "../api/types";

export const CHAIN_MODE_OPTIONS: { value: ChainMode; label: string; description: string }[] = [
  { value: "cut_each", label: "Cut each", description: "Every label cut separately. Most tape used." },
  // UNVERIFIED until checkpoint 2.
  { value: "chain_ff", label: "Chain", description: "Printed end to end, one cut at the end. Saves tape." },
  // UNVERIFIED until checkpoint 2.
  { value: "strip_marks", label: "One strip", description: "Single strip with printed guides. Cut them yourself." },
];
