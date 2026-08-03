/** ArrowDown/ArrowUp's step size in an option grid: the number of tracks
 * the grid is CURRENTLY laid out into, so the keys move a full ROW rather
 * than always +-1 (L12, docs/code-review-2026-08.md) -- an 8-column grid
 * should drop one row per ArrowDown, not one icon right (ArrowRight's own
 * behavior). A real browser resolves `getComputedStyle(grid)
 * .gridTemplateColumns` to a space-separated list of concrete per-track
 * pixel widths once layout has run -- even for an `auto-fill`/`minmax(...)`
 * track list, e.g. "72px 72px 72px 72px" -- one token per column, counted
 * here. jsdom has no layout/CSS engine at all, so `getComputedStyle` here
 * always reports an EMPTY string instead (a real browser would report the
 * property's own CSS-wide initial value "none" for an out-of-DOM or
 * not-yet-laid-out element -- also handled below) -- either way that
 * parses to zero tokens, and the fallback is exactly 1, so every
 * jsdom-based keyboard-nav test in SymbolBrowser.test.tsx (H7 included)
 * keeps the original +-1 semantics it was written against, while a real
 * browser gets true row-wise navigation. Lives in lib/ (not the component
 * file) so both fallback paths can be exercised directly without tripping
 * react-refresh/only-export-components. */
export function columnCount(grid: HTMLElement | null): number {
  if (!grid) return 1;
  const tracks = getComputedStyle(grid)
    .gridTemplateColumns.trim()
    .split(/\s+/)
    .filter((track) => track !== "" && track !== "none");
  return tracks.length > 0 ? tracks.length : 1;
}
