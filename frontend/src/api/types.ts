// Types mirroring the backend API contract (backend/src/labelmaker/api/*.py).
// Keep in lockstep with that source, not with the task brief's summary of it.

import type { JsonSchemaObject } from "../schema/jsonSchema";

export type TapeFamily = "tze" | "hse_2_1" | "hse_3_1";

export interface Tape {
  width_mm: number;
  family: TapeFamily;
}

/** A label definition as sent to /api/render/preview and /api/print.
 * `params` is intentionally untyped at this layer (backend/render/document.py's
 * LabelDefinition.params is a bare dict, validated server-side against the
 * chosen type's own Params model) -- TextLabelParams below is this app's own
 * view of the one type ("text") the designer currently authors. */
export interface LabelDefinition {
  type: string;
  tape: Tape;
  params: Record<string, unknown>;
}

export type HAlign = "left" | "center" | "right";

/** Mirrors backend/render/types/text_label.py's SymbolIcon -- a bundled
 * Material Symbols icon (see GET /api/symbols for valid `id`s). */
export interface SymbolIcon {
  kind: "symbol";
  id: string;
}

/** Mirrors backend/render/types/text_label.py's ImageIcon -- a previously
 * uploaded image (see POST /api/images, which returns the `image_id` this
 * carries). `mode="threshold"` binarizes at a fixed cutoff (hard edges);
 * `mode="dither"` Floyd-Steinberg halftones it (better for photos/
 * gradients) -- see render/images.py's module docstring. */
export interface ImageIcon {
  kind: "image";
  image_id: string;
  mode: "threshold" | "dither";
  threshold: number;
}

/** Mirrors backend/render/types/text_label.py's `Icon` discriminated union
 * (discriminator: `kind`). Optional leading art at the left of a "text"
 * label's text block, square, sized to (print height - 2*padding); text
 * shifts right to make room -- see that module's docstring. */
export type Icon = SymbolIcon | ImageIcon;

/** Mirrors backend/render/types/text_label.py's TextLabelParams. */
export interface TextLabelParams {
  lines: string[];
  font_family: string;
  bold: boolean;
  font_size_px: number | null;
  h_align: HAlign;
  length_mm: number | null;
  padding_mm: number;
  icon?: Icon | null;
  [key: string]: unknown;
}

export interface HealthResponse {
  status: string;
  printer_mode: "mock" | "usb";
  /** task 4.2: this app's own installed version (backend/main.py's
   * APP_VERSION, read from pyproject.toml via importlib.metadata) -- the
   * Diagnostics page's "App" section shows this next to backend
   * reachability. */
  version: string;
}

export interface LabelTypeInfo {
  type: string;
  title: string;
  /** Grouping for a future type picker: "general" for freeform text types,
   * "network" for patch_panel/punch_down/faceplate, "electrical" for
   * terminal_block/breaker_box, more later. Not yet consumed by any UI
   * (2.10 does). */
  category: string;
  /** None (null) = usable on any tape width. Not yet consumed by any UI. */
  min_tape_mm: number | null;
  /** pydantic's `model_json_schema()` output for this type's own Params
   * model -- task 2.10's schema-driven form renderer (src/schema/,
   * src/components/schema/) walks this directly. See
   * src/schema/jsonSchema.ts's module docstring for exactly which JSON
   * Schema shapes it's verified against (the 9 real types' live output,
   * fixtured at src/test/fixtures/label-types.json). */
  params_schema: JsonSchemaObject;
}

/** Mirrors backend/render/fonts.py's FontInfo -- GET /api/fonts. */
export interface FontInfo {
  family: string;
  display_name: string;
  monospace: boolean;
  has_bold: boolean;
}

/** Mirrors backend/api/router_labels.py's TapeInfo -- GET /api/tapes. */
export interface TapeInfo {
  nominal_mm: number;
  family: TapeFamily;
  print_dots: number;
  print_mm: number;
  max_length_mm: number;
}

/** Mirrors backend/render/symbols.py's SymbolInfo -- one entry of
 * GET /api/symbols' curated Material Symbols catalog. `id` is what an
 * `Icon` of `kind: "symbol"` carries; `path` (an `<id>.svg` filename under
 * backend/assets/symbols/) is informational only -- fetch the SVG itself
 * via GET /api/symbols/{id}, not by constructing this path client-side. */
export interface SymbolInfo {
  id: string;
  name: string;
  tags: string[];
  path: string;
}

/** POST /api/images' response (task 2.7): `image_id` is what an `Icon` of
 * `kind: "image"` carries. `width`/`height` are the NORMALIZED (RGBA
 * flattened onto white, converted to PNG) stored image's dimensions, not
 * necessarily the originally-uploaded file's encoding. */
export interface ImageUploadResponse {
  image_id: string;
  width: number;
  height: number;
}

export type WarningSeverity = "info" | "warning";

/** Mirrors backend/render/document.py's RenderWarning. Match on `code`,
 * never on `message` text -- message is UI-display-only prose that can
 * change wording freely. */
export interface RenderWarning {
  code: string;
  severity: WarningSeverity;
  message: string;
  object_id: string | null;
}

/** Mirrors backend/render/serialize.py's SequenceKind/Collation -- see that
 * module's docstring for the BarTender-model expansion (task 2.4):
 * effective_count (Sequence.count for numeric/alpha, or values.length /
 * rows.length for list/csv) DISTINCT values, each repeated
 * copies_per_value times, either grouped adjacent to each other
 * (copies_adjacent: v1,v1,v2,v2 -- the default) or with the whole distinct
 * run repeated (sequence_repeated: v1,v2,v1,v2). */
export type SequenceKind = "numeric" | "alpha" | "list" | "csv";
export type Collation = "copies_adjacent" | "sequence_repeated";

/** Mirrors backend/render/serialize.py's Sequence. Every field besides
 * `kind` has a server-side default (see serialize.py's Field(...) defaults)
 * and is therefore optional here too -- which fields actually matter
 * depends on `kind`: numeric reads start/step/pad_width/count, alpha reads
 * alpha_start/step/count, list reads `values` (count is ignored, derived
 * as values.length), csv reads `rows` (count likewise ignored, derived as
 * rows.length; each row additionally binds its own columns into template
 * text via {csv.<col>} tokens -- see expand_tokens). */
export interface Sequence {
  kind: SequenceKind;
  count?: number;
  copies_per_value?: number;
  collation?: Collation;
  start?: number;
  step?: number;
  pad_width?: number;
  alpha_start?: string;
  values?: string[];
  rows?: Record<string, string>[];
}

/** POST /api/render/expand's request body -- no rendering, just the
 * distinct values a Sequence produces (and, optionally, `sample` expanded
 * against each of them for UI-chip previews). */
export interface ExpandRequest {
  serialization: Sequence;
  sample?: string | null;
}

/** POST /api/render/expand's response. `values` are the DISTINCT sequence
 * values, in order, with NO copies applied (see serialize.py's
 * sequence_values) -- `total_labels` already accounts for
 * copies_per_value. `samples` is `sample` expanded against each distinct
 * value (first 24 max, for UI chips) -- present only when `sample` was
 * given in the request, null otherwise. */
export interface ExpandResponse {
  values: string[];
  total_labels: number;
  samples: string[] | null;
}

/** POST /api/serialize/csv's response: a stateless echo of an uploaded
 * CSV file, parsed with columns/rows/row_count -- `rows` is directly
 * postable, unmodified, as a Sequence's `rows` field (kind: "csv"). */
export interface CsvUploadResponse {
  columns: string[];
  rows: Record<string, string>[];
  row_count: number;
}

export interface PreviewRequest {
  definition: LabelDefinition;
  scale?: number;
  /** task 2.4: when set, `definition` is treated as a TEMPLATE and `index`
   * selects which of its expanded labels to render (422 if index is out of
   * range) -- see backend/api/router_labels.py's render_preview. */
  serialization?: Sequence | null;
  index?: number;
}

/** UNIT TRAP: png_width_px/png_height_px are the SCALED PNG dimensions
 * (device dots x scale) -- see router_labels.py's _render_and_encode.
 * length_mm is the physical label length (backend/driver/geometry.dots_to_mm
 * of the UNscaled render width). Never derive mm from the png_* fields;
 * always read length_mm directly. `min_feed_mm` (task 2.9) is the mechanical
 * head-to-cutter feed floor (backend/driver/geometry.MIN_FEED_MM, currently
 * 24.5) -- any label under it still consumes that much tape; when
 * `length_mm < min_feed_mm`, `warnings` also carries a `code: "short_label"`
 * entry (severity "info") saying so. */
export interface PreviewResponse {
  png_b64: string;
  png_width_px: number;
  png_height_px: number;
  length_mm: number;
  min_feed_mm: number;
  warnings: RenderWarning[];
  /** Non-null only when the request included `serialization` -- the
   * expanded total label count / the sequence value that produced the
   * rendered `index`, respectively. */
  total_labels: number | null;
  sequence_value: string | null;
}

export type ChainMode = "cut_each" | "chain_ff" | "strip_marks";

export interface PrintOptions {
  chain_mode: ChainMode;
  margin_mm: number;
  auto_cut: boolean;
}

export interface PrintRequest {
  labels: LabelDefinition[];
  options?: Partial<PrintOptions>;
  /** task 2.4: when set, `labels` must contain exactly ONE template
   * definition (422 otherwise) -- the server expands it via
   * `serialization` into `label_count` labels at render time (see
   * backend/render/serialize.py and jobs/worker.py). The job snapshot
   * stores the template + this spec UNEXPANDED, so reprint re-expands
   * reproducibly rather than replaying an already-expanded list. */
  serialization?: Sequence | null;
}

export interface PrintJobResponse {
  job_id: string;
}

// --- Tape estimate (task 2.9) ------------------------------------------
// Mirrors backend/render/estimate.py's TapeEstimate -- see that module's
// docstring for the full per-chain-mode model and constant provenance.

/** How much physical tape a job (or a hypothetical one, via POST
 * /api/print/estimate) consumes. `label_lengths_mm` is each label's
 * rendered length, in the same order the job's labels expand to;
 * `content_mm` is their sum; `feed_overhead_mm` is everything else
 * (leader/margin/cut-mark waste, `total_mm - content_mm`); `per_label_mm`
 * is `total_mm / label_lengths_mm.length`, a convenience for the UI.
 * `notes` are human-readable explanations of where the overhead comes
 * from (e.g. chaining savings, the 24.5mm minimum-feed floor). */
export interface TapeEstimate {
  label_lengths_mm: number[];
  content_mm: number;
  feed_overhead_mm: number;
  total_mm: number;
  per_label_mm: number;
  notes: string[];
}

/** POST /api/print/estimate's response: the SAME body POST /api/print
 * accepts (labels/options/serialization), returned as a TapeEstimate plus
 * the expanded `label_count` -- WITHOUT creating a job (no history entry,
 * nothing enqueued). This is what a "how much tape will this use?" UI
 * (the JobTray) calls before committing to an actual print. */
export interface PrintEstimateResponse extends TapeEstimate {
  label_count: number;
}

export type JobStatus = "queued" | "printing" | "done" | "failed" | "canceled";

export interface PrintJob {
  id: string;
  created_at: string;
  status: JobStatus;
  error: string | null;
  definition: unknown;
  label_count: number;
  chain_mode: string;
  strategy: string | null;
  tape_width_mm: number | null;
  media_raw_byte: number | null;
  tape_used_mm: number | null;
  thumbnail_png_b64: string | null;
}

// --- Presets (task 2.8) -----------------------------------------------------
// Mirrors backend/api/router_presets.py + db/database.py's presets table.
// A preset's `definition` is the label TYPE's own `params` shape (e.g.
// TextLabelParams for label_type="text") -- NOT a full LabelDefinition
// (type+tape+params). `label_type`/`tape_width_mm`/`tape_family` are
// separate, independently-settable fields: `label_type` says which type
// `definition` is validated against; `tape_width_mm` is an OPTIONAL
// tape-width hint (null = "any tape") and `tape_family` is NOT nullable
// ("tze" default, review fix-up) -- both are validated together against
// the real tape table server-side (422 at create/update on an impossible
// combination). POST /api/presets/{id}/print builds a job's Tape from
// those two UNLESS the request body supplies its own `tape` (which always
// wins -- the only way to print an "any tape" preset, or a different tape
// than the one saved).

export interface Preset {
  id: string;
  name: string;
  label_type: string;
  definition: Record<string, unknown>;
  tape_width_mm: number | null;
  tape_family: TapeFamily;
  favorite: boolean;
  created_at: string;
  updated_at: string;
}

/** POST /api/presets' request body -- 201 with the created Preset. */
export interface PresetCreateRequest {
  name: string;
  label_type: string;
  definition: Record<string, unknown>;
  tape_width_mm?: number | null;
  tape_family?: TapeFamily;
  favorite?: boolean;
}

/** PUT /api/presets/{id}'s request body: every field optional (a true
 * partial update -- an OMITTED field is left untouched server-side). Of
 * the fields that ARE sent explicitly as `null`, only `tape_width_mm` is
 * actually nullable server-side (clears back to "any tape") -- `name`/
 * `label_type`/`favorite`/`tape_family` are all non-nullable and 422 if
 * sent as explicit null (review fix-up: previously a 500 for `name`/
 * `label_type`, or a silent no-op clear for `favorite`). */
export interface PresetUpdateRequest {
  name?: string;
  label_type?: string;
  definition?: Record<string, unknown>;
  tape_width_mm?: number | null;
  tape_family?: TapeFamily;
  favorite?: boolean;
}

/** POST /api/presets/{id}/print's request body -- every field optional
 * (the whole body may be omitted entirely); `options`/`serialization`
 * mirror PrintRequest's own split minus `labels` (built server-side from
 * the preset). `tape`, when given, always overrides the preset's own
 * tape_width_mm/tape_family (review fix-up) -- required to print an "any
 * tape" preset (tape_width_mm is null) at all. Same 202 `{job_id}`
 * contract as POST /api/print. */
export interface PresetPrintRequest {
  options?: Partial<PrintOptions>;
  serialization?: Sequence | null;
  tape?: Tape | null;
}

// --- History (task 2.8) ------------------------------------------------------
// Mirrors backend/api/router_history.py.

/** GET /api/history's list item -- a deliberately LIGHT shape (Phase-1
 * review's "split the job resource" note): no `definition` (can be large --
 * up to 1000 expanded labels' worth for a serialized run) and no inline
 * base64 thumbnail bytes. `thumbnail_url`, when non-null, is a fetchable
 * GET /api/history/{id}/thumbnail path (raw PNG bytes, not JSON). */
export interface HistoryItem {
  id: string;
  created_at: string;
  status: JobStatus;
  error: string | null;
  label_count: number;
  chain_mode: string;
  strategy: string | null;
  tape_width_mm: number | null;
  tape_used_mm: number | null;
  thumbnail_url: string | null;
}

export interface HistoryListResponse {
  items: HistoryItem[];
  page: number;
  page_size: number;
  total: number;
}

/** GET /api/history's query params -- all optional. `q` is a raw,
 * case-insensitive substring match against the stored definition JSON (no
 * field-aware search -- see db/database.py's list_jobs docstring). */
export interface HistoryListParams {
  page?: number;
  page_size?: number;
  status?: JobStatus;
  q?: string;
}

/** GET /api/history/{id}'s response: the FULL job resource, same shape as
 * GET /api/print/jobs/{id} (both handlers share router_print.py's
 * `_job_to_response`) -- includes `definition` and the inline base64
 * thumbnail, unlike GET /api/history's light list items above. */
export type HistoryJob = PrintJob;

/** POST /api/history/{id}/reprint's response -- same 202 `{job_id}` shape
 * as POST /api/print; the new job gets its own id and a COPIED definition,
 * re-rendered from the original's stored snapshot. */
export type ReprintResponse = PrintJobResponse;

export interface PrinterStatusDetail {
  model_code: number;
  series_code: number;
  country_code: number;
  error_info1: number;
  error_info2: number;
  media_width_mm: number;
  media_type_raw: number;
  media_type: number | null;
  number_of_colors: number;
  status_type_raw: number;
  status_type: number | null;
  phase_type: number;
  phase_number: number;
  tape_color_raw: number;
  text_color_raw: number;
  raw_hex: string;
  errors: string[];
  has_error: boolean;
  is_e720bt: boolean;
}

/** commit 6: the optional keep-awake poller's own status (additive field on
 * GET /api/printer/status) -- see backend/jobs/keepalive.py. `last_result`
 * is `null` only before the poller's very first attempt (e.g. right after
 * boot, or whenever it's never been enabled); once it has attempted at
 * least once, `last_attempt_at`/`last_result` keep the most recent
 * attempt's outcome even while currently disabled or inert (mock mode). */
export interface KeepAliveStatus {
  enabled: boolean;
  last_attempt_at: string | null;
  last_result: "ok" | "skipped_busy" | "error" | null;
  last_error: string | null;
}

export interface PrinterStatusResponse {
  connected: boolean;
  printer_mode: "mock" | "usb";
  status: PrinterStatusDetail | null;
  error: string | null;
  keep_alive: KeepAliveStatus;
}

export type JobEventType =
  | "job.queued"
  | "job.started"
  | "job.done"
  | "job.failed"
  | "job.canceled"
  | "job.progress";

/** `error` is present on `job.failed`; `sent`/`total` (task 2.9, in bytes
 * of the job's wire stream) are present on `job.progress` -- broadcast at
 * most ~11 times per job (throttled by 10-percentage-point increments,
 * see backend/jobs/worker.py's _make_progress_cb), strictly increasing,
 * always ending with `sent === total`. */
export interface JobEvent {
  event: JobEventType;
  job_id: string;
  error?: string;
  sent?: number;
  total?: number;
}

/** FastAPI's shape for an HTTPException(detail=<string>) our routes raise on
 * 422 (router_labels.py/router_print.py's error_message()) -- but automatic
 * pydantic request-validation failures come back as `detail: ValidationIssue[]`
 * instead, so both are modeled here (see extractErrorDetail in client.ts). */
export interface ValidationIssue {
  loc: (string | number)[];
  msg: string;
  type: string;
}

export interface ApiErrorBody {
  detail?: string | ValidationIssue[];
}

/** Mirrors backend/render/gallery.py's GalleryItem -- one curated example
 * card from GET /api/gallery (task 2.14). `type`+`params`+`tape` are what
 * "Open in designer" loads into the designer store; `min_feed_mm` mirrors
 * PreviewResponse's field of the same name (DeckStrip needs it);
 * `total_labels`/`sequence_value` are non-null only for a serialized
 * {seq}-template entry (which instance of the run is pictured -- always
 * the first). */
export interface GalleryItem {
  id: string;
  title: string;
  blurb: string;
  type: string;
  tape: Tape;
  params: Record<string, unknown>;
  length_mm: number;
  png_b64: string;
  min_feed_mm: number;
  warnings: RenderWarning[];
  total_labels: number | null;
  sequence_value: string | null;
}

// --- HomeBox (task 3.4) --------------------------------------------------
// Mirrors backend/api/router_homebox.py + backend/homebox/client.py's own
// response models. That client's `_ApiModel` parses HomeBox's camelCase wire
// shape via `validation_alias` only (never a plain `alias`), so every field
// name below -- including nested ones -- is already snake_case by the time
// it crosses the proxy; there is no camelCase form to also model here.

/** GET /api/homebox/status -- always 200 (see that route's own docstring):
 * the frontend's entire show/hide signal for HomeBox UI, both the AppShell
 * nav item and the /homebox route's own state machine. `reachable`/
 * `healthy`/`version` are null together only when `configured` is false;
 * `reachable: false` (HomeBox down/unreachable/bad key) leaves `healthy`
 * null too (never got far enough to ask); `healthy: false` with
 * `reachable: true` is the pre-v0.26 API-generation mismatch, `error`
 * carrying the upgrade instructions. */
export interface HomeboxStatus {
  configured: boolean;
  reachable: boolean | null;
  healthy: boolean | null;
  version: string | null;
  error: string | null;
}

/** Mirrors homebox/client.py's EntityTypeSummary -- the item-vs-location
 * discriminator in the unified entities API. */
export interface HomeboxEntityType {
  id: string;
  name: string;
  is_location: boolean;
}

/** Mirrors homebox/client.py's TagSummary. */
export interface HomeboxTag {
  id: string;
  name: string;
  color: string;
}

/** Mirrors homebox/client.py's EntitySummary -- the list/search/asset-lookup
 * row shape. `parent` is the immediate container (recursively another
 * summary), NOT the nearest LOCATION ancestor -- that's what
 * GET /api/homebox/entities/{id}/path (HomeboxPathSegment[] below) is for. */
export interface HomeboxEntitySummary {
  id: string;
  name: string;
  description: string;
  asset_id: string;
  archived: boolean;
  quantity: number | null;
  entity_type: HomeboxEntityType | null;
  parent: HomeboxEntitySummary | null;
  tags: HomeboxTag[];
  thumbnail_id: string | null;
  image_id: string | null;
}

/** Mirrors homebox/client.py's Entity (GET /api/homebox/entities/{id}) --
 * every EntitySummary field plus the single-entity extras. */
export interface HomeboxEntity extends HomeboxEntitySummary {
  serial_number: string;
  model_number: string;
  manufacturer: string;
  notes: string;
  children: HomeboxEntitySummary[];
}

/** Mirrors homebox/client.py's EntityPage -- GET /api/homebox/entities'
 * response. */
export interface HomeboxEntityPage {
  items: HomeboxEntitySummary[];
  page: number;
  page_size: number;
  total: number;
}

/** Mirrors homebox/client.py's TreeItem -- one node of
 * GET /api/homebox/entities/tree. `type` is HomeBox's own lowercase
 * "location"/"item" vocabulary. */
export interface HomeboxTreeItem {
  id: string;
  name: string;
  type: string;
  children: HomeboxTreeItem[];
}

/** Mirrors homebox/client.py's PathSegment -- one ancestor in
 * GET /api/homebox/entities/{id}/path's root-first chain (the entity itself
 * is the LAST segment, per that route's own docstring). */
export interface HomeboxPathSegment {
  id: string;
  name: string;
  type: string;
}

/** GET/PUT /api/homebox/settings -- `qr_base_url` is the stored override
 * (null when unset); `effective_qr_base_url` already falls back to
 * `config.homebox_url` server-side (see router_homebox.py's
 * `_settings_response`) and is null only when NEITHER is configured --
 * callers building a label's `qr_data` read this field, never
 * `qr_base_url` directly, and must never fabricate a base URL when it's
 * null. */
export interface HomeboxSettings {
  qr_base_url: string | null;
  effective_qr_base_url: string | null;
}

/** PUT /api/homebox/settings' request body (task 4.2's Settings page).
 * `null` clears the stored override back to the config.homebox_url
 * fallback -- mirrors backend/api/router_homebox.py's
 * HomeBoxSettingsUpdate; the max_length=255 / http(s)-scheme / no-
 * whitespace checks are all server-side (a 422's `detail` comes back
 * through the same extractErrorDetail path as every other route). */
export interface HomeboxSettingsUpdate {
  qr_base_url: string | null;
}

// --- Auth (task 4.1) -------------------------------------------------------
// Mirrors backend/api/router_auth.py + api/auth_gate.py.

/** The subset of the IdP's id_token claims this app actually keeps in the
 * session (api/router_auth.py's callback) -- `name`/`email` are whatever the
 * IdP itself sent (either can legitimately be missing depending on the
 * `oidc_scopes` the IdP honors), `exp` is the id_token's own expiry
 * (seconds since epoch), re-checked server-side on every request (see
 * `auth_gate.get_session_user`) -- this app never re-derives it client-side. */
export interface AuthUser {
  sub: string | null;
  name: string | null;
  email: string | null;
  exp: number | null;
}

/** GET /api/auth/me's response -- the ONE probe hooks/useAuth.ts needs, in
 * EITHER auth mode: mode "none" always answers a CONSTANT
 * `{auth_mode: "none", authenticated: true, user: null}` (see that route's
 * own docstring), so callers should branch on this shape, never on
 * `auth_mode` fetched/cached separately. */
export interface AuthMe {
  auth_mode: "none" | "oidc";
  authenticated: boolean;
  user: AuthUser | null;
}

// --- Settings (task 4.5) ----------------------------------------------------
// Mirrors backend/api/router_settings.py + backend/settings_overlay.py: a
// DB-backed overlay over AppConfig an operator can edit from the Settings
// page, with no restart. GET/PUT /api/settings both return the SAME
// `{settings: SettingRow[]}` shape -- an ALLOWLIST, not a config dump, so a
// server-side field addition later is a conscious, reviewed change on
// BOTH ends, not a silent drift. Never oidc_*/session_*/the raw
// homebox_api_key value -- see that module's own docstring for why.

export type SettingsSource = "db" | "env" | "default";

/** One row. `editable: true` rows are settings_overlay.SettingsOverrides'
 * own fields -- every one of them carries `value` EXCEPT `homebox_api_key`,
 * which carries `set: boolean` instead and NEVER `value` (the secret is
 * never echoed back to the browser, in any provenance state).
 * `editable: false` rows are read-only, informational AppConfig fields
 * (auth_mode/els_enabled/data_dir/cors_origins) -- always `value`, no
 * `set`. `source` is `"db"` when a stored override is active, `"env"` when
 * AppConfig itself resolved the field from an explicitly-set env var,
 * `"default"` otherwise. */
export interface SettingRow {
  key: string;
  value?: string | number | boolean | string[] | null;
  set?: boolean;
  source: SettingsSource;
  editable: boolean;
}

/** GET/PUT /api/settings' response shape. */
export interface SettingsResponse {
  settings: SettingRow[];
}

/** PUT /api/settings' request body: a partial map of `{field: value |
 * null}` -- an omitted field is left untouched server-side; `null` reverts
 * that field to its env/default value (clears the DB override). Every key
 * must be one of SettingsOverrides' own fields (backend/settings_overlay.py)
 * -- an unknown key, or a value outside that field's own bounds/Literal
 * choices, 422s (parsed the same readable way as every other route, see
 * extractErrorDetail in client.ts). */
export type SettingsUpdate = Record<string, string | number | boolean | null>;
