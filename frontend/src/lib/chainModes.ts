// Plain-language descriptions per the design doc's copy voice ("what the
// user gets, not protocol jargon"). chain_ff/strip_marks' underlying tape
// math is UNVERIFIED until the physical checkpoint (see backend/render/
// estimate.py's own module docstring) -- that caveat stays in code
// comments only, never in this user-facing copy.
//
// Lives in lib/ (not TrayPanel.tsx, where this was originally defined) so
// this copy can be shared, without a component-to-component import, by
// BOTH TrayPanel.tsx's own Mode control (the only place chain mode can be
// changed) and PrintPreviewDeck.tsx's own read-only mode label (mode
// unification: the deck has no mode control of its own) -- AppShell.tsx,
// not TrayPanel.tsx, is what actually mounts PrintPreviewDeck.tsx, but
// even so, re-exporting this from TrayPanel.tsx would tangle two otherwise
// independent components together (and trip react-refresh/only-export-
// components, which requires a component file to export components only).
import type { ChainMode } from "../api/types";

export const CHAIN_MODE_OPTIONS: { value: ChainMode; label: string; description: string }[] = [
  { value: "cut_each", label: "Cut each", description: "Every label cut separately. Most tape used." },
  // UNVERIFIED until checkpoint 2.
  { value: "chain_ff", label: "Cut at end", description: "Printed end to end, one cut at the end. Saves tape." },
  // UNVERIFIED until checkpoint 2.
  { value: "strip_marks", label: "One strip", description: "Single strip with printed guides. Cut them yourself." },
];
