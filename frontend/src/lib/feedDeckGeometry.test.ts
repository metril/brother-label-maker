import { describe, expect, it } from "vitest";
import { computeFeedDeckGeometry, DEFAULT_PX_PER_MM, PX_PER_MM } from "./feedDeckGeometry";

describe("computeFeedDeckGeometry", () => {
  it("derives the strip width from length_mm alone -- a case where deriving from the PNG's own pixel aspect ratio would give a different (wrong) answer", () => {
    // A scale-2 render of a 54.2mm-long label on 24mm tape: the PNG's own
    // pixel dims (png_width_px/png_height_px) would be roughly
    // 54.2*2*DOTS_PER_MM x 128*2 -- a naive width_px/height_px-derived mm
    // figure (especially if the caller forgot to divide out `scale`) would
    // NOT equal 54.2. This asserts the geometry only ever consumes the
    // physical lengthMm the caller passes, never anything PNG-shaped.
    const geo = computeFeedDeckGeometry(54.2, 24, 18.1, 24.5);
    expect(geo.stripWidthPx).toBeCloseTo(54.2 * PX_PER_MM);
    expect(geo.stripHeightPx).toBe(24 * PX_PER_MM);
  });

  it("insets the printable band from the tape's own print_mm, centered with an equal margin on each side", () => {
    const geo = computeFeedDeckGeometry(40, 24, 18.1, 24.5);
    expect(geo.printableHeightPx).toBeCloseTo(18.1 * PX_PER_MM);
    expect(geo.marginHeightPx).toBeCloseTo((24 * PX_PER_MM - 18.1 * PX_PER_MM) / 2);
  });

  it("only produces a minimum-feed waste region when length_mm is under the floor, sized to reach exactly the floor", () => {
    const short = computeFeedDeckGeometry(10, 24, 18.1, 24.5);
    expect(short.feedWasteMm).toBeCloseTo(14.5);
    expect(short.feedWasteWidthPx).toBeCloseTo(14.5 * PX_PER_MM);
    expect(short.totalWidthPx).toBeCloseTo(24.5 * PX_PER_MM);

    const long = computeFeedDeckGeometry(40, 24, 18.1, 24.5);
    expect(long.feedWasteMm).toBe(0);
    expect(long.feedWasteWidthPx).toBe(0);
    expect(long.totalWidthPx).toBe(long.stripWidthPx);
  });

  // track C3 (Designer preview zoom): every px-shaped field must scale
  // LINEARLY with pxPerMm, and omitting it entirely must reproduce the
  // exact pre-C3 output (DEFAULT_PX_PER_MM) -- the regression Gallery's
  // DeckStrip usage (which never passes pxPerMm) relies on.
  describe("pxPerMm (track C3: Designer preview zoom)", () => {
    it("defaults to DEFAULT_PX_PER_MM (4) when omitted, matching the historical PX_PER_MM-only behavior", () => {
      const withDefault = computeFeedDeckGeometry(40, 24, 18.1, 10);
      const explicit4 = computeFeedDeckGeometry(40, 24, 18.1, 10, DEFAULT_PX_PER_MM);
      expect(DEFAULT_PX_PER_MM).toBe(4);
      expect(DEFAULT_PX_PER_MM).toBe(PX_PER_MM);
      expect(withDefault).toEqual(explicit4);
    });

    it("scales every px-shaped field linearly with pxPerMm, leaving mm-shaped fields untouched", () => {
      const at4 = computeFeedDeckGeometry(40, 24, 18.1, 30, 4);
      const at8 = computeFeedDeckGeometry(40, 24, 18.1, 30, 8);
      const at2 = computeFeedDeckGeometry(40, 24, 18.1, 30, 2);

      for (const field of ["stripWidthPx", "stripHeightPx", "printableHeightPx", "marginHeightPx", "cutLineXPx", "feedWasteWidthPx", "totalWidthPx"] as const) {
        expect(at8[field]).toBeCloseTo(at4[field] * 2);
        expect(at2[field]).toBeCloseTo(at4[field] / 2);
      }

      // feedWasteMm is a physical mm figure, not a px figure -- must NOT
      // change with zoom.
      expect(at2.feedWasteMm).toBe(at4.feedWasteMm);
      expect(at8.feedWasteMm).toBe(at4.feedWasteMm);
    });
  });
});
