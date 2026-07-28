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
  HttpResponse.json({ status: "ok", printer_mode: "mock", version: "0.1.0" }),
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

// -- task 2.11: POST /api/render/expand + POST /api/serialize/csv --
// Reimplements just enough of backend/render/serialize.py's expansion
// model (sequence_values/effective_count/total_labels/expand_tokens) in
// JS to give SequenceEditor/Designer's serialization tests a REALISTIC
// mock -- computed from whatever Sequence body a test actually posts,
// rather than one fixed canned response every test would have to
// override. Deliberately a light reimplementation (e.g. no ALPHA
// under/overflow check, unknown {csv.<col>} passes through untouched)
// -- tests that need those specific server-side failures override with
// server.use(...) for that one case, same as everywhere else in this file.

function mockOrdinal(letters: string): number {
  let n = 0;
  for (const ch of letters) n = n * 26 + (ch.charCodeAt(0) - 65 + 1);
  return n - 1;
}

function mockToAlpha(ordinal: number): string {
  let n = ordinal + 1;
  let letters = "";
  while (n > 0) {
    const rem = (n - 1) % 26;
    letters = String.fromCharCode(65 + rem) + letters;
    n = Math.floor((n - 1) / 26);
  }
  return letters;
}

interface MockSequence {
  kind: "numeric" | "alpha" | "list" | "csv";
  count?: number;
  copies_per_value?: number;
  start?: number;
  step?: number;
  pad_width?: number;
  alpha_start?: string;
  values?: string[];
  rows?: Record<string, string>[];
}

function mockSequenceValues(seq: MockSequence): string[] {
  if (seq.kind === "numeric") {
    const count = seq.count ?? 1;
    const start = seq.start ?? 1;
    const step = seq.step ?? 1;
    const pad = seq.pad_width ?? 0;
    return Array.from({ length: count }, (_, i) => {
      const n = start + i * step;
      const sign = n < 0 ? "-" : "";
      return sign + String(Math.abs(n)).padStart(pad, "0");
    });
  }
  if (seq.kind === "alpha") {
    const count = seq.count ?? 1;
    const base = mockOrdinal(seq.alpha_start ?? "A");
    const step = seq.step ?? 1;
    return Array.from({ length: count }, (_, i) => mockToAlpha(base + i * step));
  }
  if (seq.kind === "list") return seq.values ?? [];
  return (seq.rows ?? []).map((_, i) => String(i + 1));
}

function mockEffectiveCount(seq: MockSequence): number {
  if (seq.kind === "numeric" || seq.kind === "alpha") return seq.count ?? 1;
  if (seq.kind === "list") return (seq.values ?? []).length;
  return (seq.rows ?? []).length;
}

function mockTotalLabels(seq: MockSequence): number {
  return mockEffectiveCount(seq) * (seq.copies_per_value ?? 1);
}

function mockExpandTokens(text: string, value: string, row: Record<string, string> | null): string {
  return text.replace(/\{seq\}|\{csv\.([^}]+)\}/g, (match, column: string | undefined) => {
    if (match === "{seq}") return value;
    if (row && column !== undefined && column in row) return row[column]!;
    return match;
  });
}

export const expandHandler = http.post("/api/render/expand", async ({ request }) => {
  const body = (await request.json()) as { serialization: MockSequence; sample?: string | null };
  const seq = body.serialization;
  const total = mockTotalLabels(seq);
  if (total > 1000) {
    return HttpResponse.json(
      {
        detail: [
          {
            loc: ["body", "serialization"],
            msg: `Value error, total labels ${total} (${mockEffectiveCount(seq)} values x ${seq.copies_per_value ?? 1} copies) exceeds the 1000 maximum`,
            type: "value_error",
          },
        ],
      },
      { status: 422 },
    );
  }
  const values = mockSequenceValues(seq);
  const rows = seq.kind === "csv" ? (seq.rows ?? []) : values.map(() => null);
  const samples =
    body.sample != null ? values.slice(0, 24).map((v, i) => mockExpandTokens(body.sample as string, v, rows[i] ?? null)) : null;
  return HttpResponse.json({ values, total_labels: total, samples });
});

// A fixed canned response, deliberately NOT reading the uploaded file's own
// bytes -- same reason uploadImageHandler above doesn't either: msw's
// `request.formData()` never resolves against a multipart body built from
// a jsdom File under this test environment (confirmed directly: it hangs
// indefinitely, not just "parses wrong"). Individual tests that care about
// specific uploaded CONTENT override with server.use(...) for that one
// case and assert on the request having been made / on the UI's reaction
// to a canned response, not on round-tripping the real file bytes.
export const serializeCsvHandler = http.post("/api/serialize/csv", () =>
  HttpResponse.json({
    columns: ["port", "label"],
    rows: [
      { port: "1", label: "Uplink" },
      { port: "2", label: "Downlink" },
    ],
    row_count: 2,
  }),
);

/** task 2.12: POST /api/print/jobs/:jobId/cancel -- default handler assumes
 * the job is still queued (200/{status:"canceled"}); individual tests
 * override with server.use() for the 409 ("already printing")/404 (unknown
 * id) cases per router_print.py's cancel_print_job. */
export const cancelPrintJobHandler = http.post("/api/print/jobs/:jobId/cancel", () =>
  HttpResponse.json({ status: "canceled" }),
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

// -- task 2.13: presets + history --
// Realistic-shaped defaults (mirroring api/router_presets.py/
// router_history.py) so most Presets/History tests need no server.use()
// at all -- individual tests override for the scenario they specifically
// care about (an empty list, a captured request body, a 404, ...), same
// convention as everywhere else in this file.

let mockPresetSeq = 0;

export const presetsListHandler = http.get("/api/presets", () => HttpResponse.json([]));

export const createPresetHandler = http.post("/api/presets", async ({ request }) => {
  const body = (await request.json()) as Record<string, unknown>;
  mockPresetSeq += 1;
  return HttpResponse.json(
    {
      id: `preset-${mockPresetSeq}`,
      name: body.name,
      label_type: body.label_type,
      definition: body.definition,
      tape_width_mm: body.tape_width_mm ?? null,
      tape_family: body.tape_family ?? "tze",
      favorite: body.favorite ?? false,
      created_at: "2026-07-27T00:00:00.000000Z",
      updated_at: "2026-07-27T00:00:00.000000Z",
    },
    { status: 201 },
  );
});

export const updatePresetHandler = http.put("/api/presets/:id", async ({ params, request }) => {
  const body = (await request.json()) as Record<string, unknown>;
  return HttpResponse.json({
    id: params.id,
    name: body.name ?? "Preset",
    label_type: body.label_type ?? "text",
    definition: body.definition ?? { lines: ["A"] },
    tape_width_mm: "tape_width_mm" in body ? body.tape_width_mm : 24,
    tape_family: body.tape_family ?? "tze",
    favorite: body.favorite ?? false,
    created_at: "2026-07-27T00:00:00.000000Z",
    updated_at: "2026-07-27T00:05:00.000000Z",
  });
});

export const deletePresetHandler = http.delete("/api/presets/:id", () => new HttpResponse(null, { status: 204 }));

export const printPresetHandler = http.post("/api/presets/:id/print", () =>
  HttpResponse.json({ job_id: "preset-print-job-1" }, { status: 202 }),
);

export const historyListHandler = http.get("/api/history", () =>
  HttpResponse.json({ items: [], page: 1, page_size: 20, total: 0 }),
);

export const historyDetailHandler = http.get("/api/history/:id", ({ params }) =>
  HttpResponse.json({
    id: params.id,
    created_at: "2026-07-27T00:00:00.000000Z",
    status: "done",
    error: null,
    definition: {
      labels: [{ type: "text", tape: { width_mm: 24, family: "tze" }, params: { lines: ["A"] } }],
      options: { chain_mode: "cut_each", margin_mm: 2.0, auto_cut: true },
    },
    label_count: 1,
    chain_mode: "cut_each",
    strategy: "classic",
    tape_width_mm: 24,
    media_raw_byte: null,
    tape_used_mm: 30,
    thumbnail_png_b64: null,
  }),
);

export const reprintHistoryHandler = http.post("/api/history/:id/reprint", () =>
  HttpResponse.json({ job_id: "reprint-job-1" }, { status: 202 }),
);

export const deleteHistoryHandler = http.delete("/api/history/:id", () => new HttpResponse(null, { status: 204 }));

// -- task 3.4: HomeBox proxy routes --
// A "configured, reachable, healthy" default (AppShell mounts
// useHomeboxStatus on EVERY page via its own nav item, so every existing
// suite that renders AppShell/App now makes this request too -- msw's
// onUnhandledRequest: "error" means a missing default here would fail
// every one of those, not just Homebox's own tests) plus empty-ish
// defaults for the rest of the surface; pages/Homebox.test.tsx overrides
// with server.use(...) for the scenarios it actually exercises, same
// convention as everywhere else in this file.

export const homeboxStatusConfiguredHandler = http.get("/api/homebox/status", () =>
  HttpResponse.json({ configured: true, reachable: true, healthy: true, version: "0.26.2", error: null }),
);

export const homeboxTreeHandler = http.get("/api/homebox/entities/tree", () => HttpResponse.json([]));

export const homeboxEntitiesHandler = http.get("/api/homebox/entities", () =>
  HttpResponse.json({ items: [], page: 1, page_size: 50, total: 0 }),
);

export const homeboxEntityPathHandler = http.get("/api/homebox/entities/:id/path", ({ params }) =>
  HttpResponse.json([{ id: params.id, name: "Entity", type: "item" }]),
);

export const homeboxAssetMatchesHandler = http.get("/api/homebox/assets/:assetId", () => HttpResponse.json([]));

export const homeboxSettingsHandler = http.get("/api/homebox/settings", () =>
  HttpResponse.json({ qr_base_url: null, effective_qr_base_url: null }),
);

/** PUT /api/homebox/settings (task 4.2's Settings page) -- a default that
 * just echoes the posted value back as both fields (mirroring
 * router_homebox.py's own no-config-fallback shape when config.homebox_url
 * is unset); pages/Settings.test.tsx overrides with server.use(...) for
 * the "captured request body" and "422" scenarios it actually asserts on. */
export const putHomeboxSettingsHandler = http.put("/api/homebox/settings", async ({ request }) => {
  const body = (await request.json()) as { qr_base_url: string | null };
  return HttpResponse.json({ qr_base_url: body.qr_base_url, effective_qr_base_url: body.qr_base_url });
});

// -- task 4.1: optional OIDC auth --
// AppShell mounts useAuth() on EVERY page (same reasoning as the HomeBox
// status handler above), so a mode-"none" default here is required for
// every existing suite to keep passing, not just this task's own tests.
// AppShell.test.tsx overrides with server.use(...) for the oidc-mode
// scenarios it actually exercises.

export const authMeNoneHandler = http.get("/api/auth/me", () =>
  HttpResponse.json({ auth_mode: "none", authenticated: true, user: null }),
);

export const authLogoutHandler = http.post(
  "/api/auth/logout",
  () => new HttpResponse(null, { status: 204 }),
);

// -- task 4.2: GET /api/settings/runtime (Settings page's read-only config
// panel) -- an "everything off/default" shape mirroring AppConfig's own
// class defaults (config.py; note printer_flip_pins defaults TRUE there
// since the 2026-07-28 hardware verification -- the backend test
// conftest deliberately pins it false for golden stability, so don't
// expect parity with that file).

export const runtimeSettingsHandler = http.get("/api/settings/runtime", () =>
  HttpResponse.json({
    printer_mode: "mock",
    printer_init_strategy: "classic",
    printer_bit_order: "msb_first",
    printer_flip_pins: true,
    els_enabled: false,
    els_tape_mm: 24.0,
    auth_mode: "none",
    homebox_configured: false,
  }),
);

/** Sane defaults for the app's own initial queries (health/label-types/
 * fonts/tapes/symbols/printer-status) plus preview/estimate/print/presets/
 * history/homebox -- individual tests override with server.use(...) for the
 * scenario they care about. */
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
  cancelPrintJobHandler,
  expandHandler,
  serializeCsvHandler,
  presetsListHandler,
  createPresetHandler,
  updatePresetHandler,
  deletePresetHandler,
  printPresetHandler,
  historyListHandler,
  historyDetailHandler,
  reprintHistoryHandler,
  deleteHistoryHandler,
  homeboxStatusConfiguredHandler,
  homeboxTreeHandler,
  homeboxEntitiesHandler,
  homeboxEntityPathHandler,
  homeboxAssetMatchesHandler,
  homeboxSettingsHandler,
  putHomeboxSettingsHandler,
  authMeNoneHandler,
  authLogoutHandler,
  runtimeSettingsHandler,
];
