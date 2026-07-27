// Types mirroring the backend API contract (backend/src/labelmaker/api/*.py).
// Keep in lockstep with that source, not with the task brief's summary of it.

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

/** Mirrors backend/render/types/text_label.py's TextLabelParams. */
export interface TextLabelParams {
  lines: string[];
  font_family: string;
  bold: boolean;
  font_size_px: number | null;
  h_align: HAlign;
  length_mm: number | null;
  padding_mm: number;
  [key: string]: unknown;
}

export interface HealthResponse {
  status: string;
  printer_mode: "mock" | "usb";
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
  params_schema: Record<string, unknown>;
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
 * always read length_mm directly. */
export interface PreviewResponse {
  png_b64: string;
  png_width_px: number;
  png_height_px: number;
  length_mm: number;
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

export interface PrinterStatusResponse {
  connected: boolean;
  printer_mode: "mock" | "usb";
  status: PrinterStatusDetail | null;
  error: string | null;
}

export type JobEventType = "job.queued" | "job.started" | "job.done" | "job.failed";

export interface JobEvent {
  event: JobEventType;
  job_id: string;
  error?: string;
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
