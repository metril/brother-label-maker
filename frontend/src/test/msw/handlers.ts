import { http, HttpResponse } from "msw";

/** A valid (if trivial) 1x1 PNG, base64-encoded -- enough for an <img src>
 * data URL in jsdom; tests never inspect its pixels. */
export const TINY_PNG_B64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=";

export const healthHandler = http.get("/api/health", () =>
  HttpResponse.json({ status: "ok", printer_mode: "mock" }),
);

export const labelTypesHandler = http.get("/api/label-types", () =>
  HttpResponse.json([
    {
      type: "text",
      title: "Text",
      category: "general",
      min_tape_mm: null,
      params_schema: { type: "object", properties: {} },
    },
  ]),
);

/** Mirrors backend/render/fonts.py's bundled four families exactly (B2:
 * GET /api/fonts) -- TextLabelForm's font <select> renders from this. */
export const fontsHandler = http.get("/api/fonts", () =>
  HttpResponse.json([
    { family: "Inter", display_name: "Inter", monospace: false, has_bold: true },
    {
      family: "Roboto Condensed",
      display_name: "Roboto Condensed",
      monospace: false,
      has_bold: true,
    },
    { family: "JetBrains Mono", display_name: "JetBrains Mono", monospace: true, has_bold: true },
    { family: "DejaVu Sans", display_name: "DejaVu Sans", monospace: false, has_bold: true },
  ]),
);

/** Mirrors backend/driver/geometry.py's all_tapes() exactly (all 15, TZe +
 * HSe -- B2: GET /api/tapes). TapeSelector filters this down to family
 * "tze" for its six-width UI. */
export const tapesHandler = http.get("/api/tapes", () =>
  HttpResponse.json([
    { nominal_mm: 3.5, family: "tze", print_dots: 24, print_mm: 3.4, max_length_mm: 1000 },
    { nominal_mm: 6, family: "tze", print_dots: 32, print_mm: 4.5, max_length_mm: 1000 },
    { nominal_mm: 9, family: "tze", print_dots: 50, print_mm: 7.1, max_length_mm: 1000 },
    { nominal_mm: 12, family: "tze", print_dots: 70, print_mm: 9.9, max_length_mm: 1000 },
    { nominal_mm: 18, family: "tze", print_dots: 112, print_mm: 15.8, max_length_mm: 1000 },
    { nominal_mm: 24, family: "tze", print_dots: 128, print_mm: 18.1, max_length_mm: 1000 },
    { nominal_mm: 5.8, family: "hse_2_1", print_dots: 28, print_mm: 4.0, max_length_mm: 500 },
    { nominal_mm: 8.8, family: "hse_2_1", print_dots: 48, print_mm: 6.8, max_length_mm: 500 },
    { nominal_mm: 11.7, family: "hse_2_1", print_dots: 66, print_mm: 9.3, max_length_mm: 500 },
    { nominal_mm: 17.7, family: "hse_2_1", print_dots: 106, print_mm: 15.0, max_length_mm: 500 },
    { nominal_mm: 23.6, family: "hse_2_1", print_dots: 128, print_mm: 18.1, max_length_mm: 500 },
    { nominal_mm: 5.2, family: "hse_3_1", print_dots: 20, print_mm: 2.8, max_length_mm: 500 },
    { nominal_mm: 9.0, family: "hse_3_1", print_dots: 44, print_mm: 6.2, max_length_mm: 500 },
    { nominal_mm: 11.2, family: "hse_3_1", print_dots: 50, print_mm: 7.1, max_length_mm: 500 },
    { nominal_mm: 21.0, family: "hse_3_1", print_dots: 120, print_mm: 16.9, max_length_mm: 500 },
  ]),
);

export const printerStatusConnectedHandler = http.get("/api/printer/status", () =>
  HttpResponse.json({
    connected: true,
    printer_mode: "mock",
    status: {
      model_code: 129,
      series_code: 48,
      country_code: 48,
      error_info1: 0,
      error_info2: 0,
      media_width_mm: 24,
      media_type_raw: 20,
      media_type: 1,
      number_of_colors: 1,
      status_type_raw: 0,
      status_type: 0,
      phase_type: 0,
      phase_number: 0,
      tape_color_raw: 144,
      text_color_raw: 8,
      raw_hex: "80 20 42 30 81 30",
      errors: [],
      has_error: false,
      is_e720bt: true,
    },
    error: null,
  }),
);

export const printerStatusDisconnectedHandler = http.get("/api/printer/status", () =>
  HttpResponse.json({
    connected: false,
    printer_mode: "usb",
    status: null,
    error: "printer not found",
  }),
);

export const previewHandler = http.post("/api/render/preview", () =>
  HttpResponse.json({
    png_b64: TINY_PNG_B64,
    png_width_px: 200,
    png_height_px: 96,
    length_mm: 25.4,
    warnings: [],
  }),
);

export const printHandler = http.post("/api/print", () =>
  HttpResponse.json({ job_id: "job-1" }, { status: 202 }),
);

export const printJobDoneHandler = http.get("/api/print/jobs/:jobId", ({ params }) =>
  HttpResponse.json({
    id: params.jobId,
    created_at: "2026-07-27T00:00:00.000000Z",
    status: "done",
    error: null,
    definition: {},
    label_count: 1,
    chain_mode: "cut_each",
    strategy: "classic",
    tape_width_mm: 24,
    media_raw_byte: null,
    tape_used_mm: null,
    thumbnail_png_b64: null,
  }),
);

export const printJobFailedHandler = http.get("/api/print/jobs/:jobId", ({ params }) =>
  HttpResponse.json({
    id: params.jobId,
    created_at: "2026-07-27T00:00:00.000000Z",
    status: "failed",
    error: "printer out of tape",
    definition: {},
    label_count: 1,
    chain_mode: "cut_each",
    strategy: "classic",
    tape_width_mm: 24,
    media_raw_byte: null,
    tape_used_mm: null,
    thumbnail_png_b64: null,
  }),
);

/** Sane defaults for the app's own initial queries (health/label-types/
 * fonts/tapes/printer-status) plus preview/print -- individual tests
 * override with server.use(...) for the scenario they care about. */
export const defaultHandlers = [
  healthHandler,
  labelTypesHandler,
  fontsHandler,
  tapesHandler,
  printerStatusConnectedHandler,
  previewHandler,
  printHandler,
  printJobDoneHandler,
];
