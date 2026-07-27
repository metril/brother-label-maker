import { http, HttpResponse } from "msw";
import fontsFixture from "../fixtures/fonts.json";
import labelTypesFixture from "../fixtures/label-types.json";
import symbolsFixture from "../fixtures/symbols.json";
import tapesFixture from "../fixtures/tapes.json";

/** A valid (if trivial) 1x1 PNG, base64-encoded -- enough for an <img src>
 * data URL in jsdom; tests never inspect its pixels. */
export const TINY_PNG_B64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=";

export const healthHandler = http.get("/api/health", () =>
  HttpResponse.json({ status: "ok", printer_mode: "mock" }),
);

/** Real params_schema JSON Schema for all 9 label types -- fixtured from a
 * live backend (scripts/gen-fixtures.mjs), NOT hand-written. Regenerate
 * with `npm run fixtures` (backend must be running) whenever a Params
 * model's shape changes. */
export const labelTypesHandler = http.get("/api/label-types", () => HttpResponse.json(labelTypesFixture));

/** Mirrors backend/render/fonts.py's bundled four families exactly (B2:
 * GET /api/fonts) -- FontFamilyField's <select> renders from this. */
export const fontsHandler = http.get("/api/fonts", () => HttpResponse.json(fontsFixture));

/** Mirrors backend/driver/geometry.py's all_tapes() exactly (all 15, TZe +
 * HSe -- B2: GET /api/tapes). TapeSelector filters this down by family. */
export const tapesHandler = http.get("/api/tapes", () => HttpResponse.json(tapesFixture));

/** The 60-icon curated Material Symbols catalog (task 2.7). */
export const symbolsHandler = http.get("/api/symbols", () => HttpResponse.json(symbolsFixture));

export const symbolSvgHandler = http.get("/api/symbols/:id", () =>
  HttpResponse.xml('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M0 0h24v24H0z"/></svg>'),
);

export const uploadImageHandler = http.post("/api/images", () =>
  HttpResponse.json({ image_id: "img-1", width: 64, height: 64 }, { status: 201 }),
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
    min_feed_mm: 24.5,
    warnings: [],
    total_labels: null,
    sequence_value: null,
  }),
);

export const printEstimateHandler = http.post("/api/print/estimate", () =>
  HttpResponse.json({
    label_count: 1,
    label_lengths_mm: [25.4],
    content_mm: 25.4,
    feed_overhead_mm: 10,
    total_mm: 35.4,
    per_label_mm: 35.4,
    notes: [],
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
 * fonts/tapes/symbols/printer-status) plus preview/estimate/print --
 * individual tests override with server.use(...) for the scenario they
 * care about. */
export const defaultHandlers = [
  healthHandler,
  labelTypesHandler,
  fontsHandler,
  tapesHandler,
  symbolsHandler,
  symbolSvgHandler,
  uploadImageHandler,
  printerStatusConnectedHandler,
  previewHandler,
  printEstimateHandler,
  printHandler,
  printJobDoneHandler,
];
