import { describe, expect, it } from "vitest";
import { computeFeedDeckGeometry, PX_PER_MM } from "./feedDeckGeometry";

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
});
