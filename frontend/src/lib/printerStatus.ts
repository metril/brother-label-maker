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

// -- Diagnostics page (task 4.2): the media-observation UI that decodes
// byte11 (media_type_raw) -- handoff §7's own phrasing. Unlike
// describeMedia above (a terse status-bar fragment that just omits
// anything it doesn't recognize), this ALWAYS returns something, and says
// so explicitly when the byte is one driver/status.py's MediaType enum
// doesn't recognize -- e.g. the reference status block's still-undecoded
// 0x14 (docs/protocol-notes.md), which is the whole reason this UI exists:
// an operator capturing `status --raw` against real hardware needs to SEE
// an unknown byte, not have it silently disappear.
const MEDIA_TYPE_DECODED_LABEL: Record<number, string> = {
  0x00: "no media",
  0x01: "laminated (TZe)",
  0x03: "non-laminated (TZe)",
  0x11: "heat-shrink 2:1",
  0x17: "heat-shrink 3:1",
  0xff: "incompatible",
};

/** `status.media_type` (backend/driver/status.py's own parse -- null when
 * the byte isn't one of the enum's known values) is the authoritative
 * "did this app recognize it" signal; `media_type_raw` is only used here
 * for the hex readout, both in the recognized and unknown cases. */
export function describeMediaTypeRaw(status: PrinterStatusDetail): string {
  const hex = `0x${status.media_type_raw.toString(16).padStart(2, "0")}`;
  if (status.media_type == null) {
    return `unknown -- byte ${hex} is not decoded by this app`;
  }
  const label = MEDIA_TYPE_DECODED_LABEL[status.media_type];
  return label ? `${label} (${hex})` : `unknown -- byte ${hex} is not decoded by this app`;
}

/** A plain-text block pasteable straight into docs/protocol-notes.md's
 * RESULTS tables (handoff §4's "raw status capture... to decode the media
 * byte") -- the Diagnostics page's copy-to-clipboard button copies exactly
 * this string. Deliberately plain lines, not JSON: this is meant for a
 * markdown table/prose, not another program. */
export function buildRawMediaReport(status: PrinterStatusDetail): string {
  return [
    `raw_hex: ${status.raw_hex}`,
    `byte10 media_width_mm: ${status.media_width_mm} (0x${status.media_width_mm.toString(16).padStart(2, "0")})`,
    `byte11 media_type_raw: ${describeMediaTypeRaw(status)}`,
    `model_code: 0x${status.model_code.toString(16).padStart(2, "0")}${status.is_e720bt ? " (E720BT)" : ""}`,
  ].join("\n");
}
