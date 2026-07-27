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
  params_schema: Record<string, unknown>;
}

export interface PreviewRequest {
  definition: LabelDefinition;
  scale?: number;
}

/** UNIT TRAP: width_px/height_px are the SCALED PNG dimensions (device dots x
 * scale) -- see router_labels.py's _render_and_encode. length_mm is the
 * physical label length (backend/driver/geometry.dots_to_mm of the
 * UNscaled render width). Never derive mm from the px fields; always read
 * length_mm directly. */
export interface PreviewResponse {
  png_b64: string;
  width_px: number;
  height_px: number;
  length_mm: number;
  warnings: string[];
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
  preview_png: string | null;
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
