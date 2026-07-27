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
      params_schema: { type: "object", properties: {} },
    },
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
    width_px: 200,
    height_px: 96,
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
    preview_png: null,
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
    preview_png: null,
  }),
);

/** Sane defaults for the app's own initial queries (health/label-types/
 * printer-status) plus preview/print -- individual tests override with
 * server.use(...) for the scenario they care about. */
export const defaultHandlers = [
  healthHandler,
  labelTypesHandler,
  printerStatusConnectedHandler,
  previewHandler,
  printHandler,
  printJobDoneHandler,
];
