import type { PrinterStatusDetail } from "../api/types";

// Mirrors backend/driver/status.py's MediaType enum values (media_type is
// that enum's raw int value, or null when the printer hasn't reported one
// this codebase recognizes) and media_family_for's LAMINATED/NON_LAMINATED
// -> TZE, HEAT_SHRINK_2_1 -> HSE_2_1, HEAT_SHRINK_3_1 -> HSE_3_1 mapping.
const MEDIA_FAMILY_LABEL: Record<number, string> = {
  0x01: "TZe",
  0x03: "TZe",
  0x11: "HSe",
  0x17: "HSe",
};

const MEDIA_LAMINATION_LABEL: Record<number, string> = {
  0x01: "laminated",
  0x03: "non-laminated",
};

/** "24mm TZe · laminated" -- the instrument-readout fragment the status bar
 * shows next to "connected" (design doc's status bar example). Returns
 * null when there's nothing meaningful to show (no status block at all). */
export function describeMedia(status: PrinterStatusDetail | null): string | null {
  if (!status) return null;
  const parts = [`${status.media_width_mm}mm`];
  if (status.media_type != null) {
    const family = MEDIA_FAMILY_LABEL[status.media_type];
    if (family) parts.push(family);
  }
  const width = parts.join(" ");
  const lamination = status.media_type != null ? MEDIA_LAMINATION_LABEL[status.media_type] : undefined;
  return lamination ? `${width} · ${lamination}` : width;
}
