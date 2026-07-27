/** On-screen px per physical mm -- applied to physical mm values ONLY
 * (length_mm, a tape's nominal_mm/print_mm from /api/tapes), NEVER to
 * png_width_px/png_height_px (those are SCALED device-dot dimensions --
 * see api/types.ts's PreviewResponse doc, the "unit trap" this whole
 * module is built around avoiding). This is the one arithmetic constant
 * the entire feed-deck signature element is built on. */
export const PX_PER_MM = 4;

export interface FeedDeckGeometry {
  /** The tape strip's own width -- the physical length actually consumed
   * by this label's content. */
  stripWidthPx: number;
  /** The tape strip's full height -- the NOMINAL tape width (e.g. 24mm),
   * not the printable band. */
  stripHeightPx: number;
  /** The printable band's height, inset within the strip -- from
   * /api/tapes' print_mm (device print dots converted to mm), always less
   * than the nominal width (a 24mm tape prints 128 dots ~= 18.1mm). */
  printableHeightPx: number;
  /** The unprintable margin's height, one on each side of the printable
   * band (stripHeightPx - printableHeightPx, split evenly). */
  marginHeightPx: number;
  /** x-position of the cut line -- at the label's own end, i.e. exactly
   * stripWidthPx. */
  cutLineXPx: number;
  /** Width of the minimum-feed "waste" region past the cut line -- 0 when
   * the label is already at or past the mechanical feed floor. */
  feedWasteWidthPx: number;
  /** Same figure in mm, for the "+X.X mm feed waste" caption. */
  feedWasteMm: number;
  /** stripWidthPx + feedWasteWidthPx -- the full on-screen width to
   * reserve/scroll for. */
  totalWidthPx: number;
}

/** Deriving the feed deck's entire geometry from three physical-mm inputs
 * (never from the preview PNG's own pixel dimensions) is the load-bearing
 * design decision here -- see PX_PER_MM's own docstring and the design
 * doc's "signature element" section. */
export function computeFeedDeckGeometry(
  lengthMm: number,
  nominalMm: number,
  printMm: number,
  minFeedMm: number,
): FeedDeckGeometry {
  const stripWidthPx = lengthMm * PX_PER_MM;
  const stripHeightPx = nominalMm * PX_PER_MM;
  const printableHeightPx = printMm * PX_PER_MM;
  const marginHeightPx = Math.max(0, (stripHeightPx - printableHeightPx) / 2);
  const feedWasteMm = Math.max(0, minFeedMm - lengthMm);
  const feedWasteWidthPx = feedWasteMm * PX_PER_MM;

  return {
    stripWidthPx,
    stripHeightPx,
    printableHeightPx,
    marginHeightPx,
    cutLineXPx: stripWidthPx,
    feedWasteWidthPx,
    feedWasteMm,
    totalWidthPx: stripWidthPx + feedWasteWidthPx,
  };
}

/** "24" not "24.0", "3.5" not "3.5000000000000004" -- for the nominal/print
 * mm values shown in the deck's own quiet caption. */
export function formatMm(mm: number): string {
  return Number.isInteger(mm) ? String(mm) : mm.toFixed(1);
}
