import type {
  ApiErrorBody,
  FontInfo,
  HealthResponse,
  ImageUploadResponse,
  LabelTypeInfo,
  PreviewRequest,
  PreviewResponse,
  PrintEstimateResponse,
  PrintJob,
  PrintJobResponse,
  PrintRequest,
  PrinterStatusResponse,
  SymbolInfo,
  TapeInfo,
  ValidationIssue,
} from "./types";

const API_BASE = "/api";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function isValidationIssueArray(detail: unknown): detail is ValidationIssue[] {
  return (
    Array.isArray(detail) &&
    detail.every((item) => typeof item === "object" && item !== null && "msg" in item)
  );
}

// Matches pydantic v2's own `str(ValidationError)` header, e.g. "1
// validation error for BreakerBoxParams" / "3 validation errors for
// TextLabelParams".
const PYDANTIC_ERROR_HEADER_RE = /^\d+ validation errors? for \S+/;
// One error "block" within that dump: a field-path line, then an indented
// message line ending in pydantic's own "[type=..., input_value=...,
// input_type=...]" tag -- see the worked example in this function's own
// docstring. The lazy `(.+?)` + literal `\[type=` anchor (not a generic
// "last bracket group") is what lets this survive a message that itself
// contains brackets, e.g. "font_size_px must be in [6, 128], got 500".
const PYDANTIC_ERROR_BLOCK_RE = /([^\n]+)\n\s+(.+?)\s*\[type=[^\]]*\]/g;

/** Turns pydantic v2's own multi-line `str(ValidationError)` dump --
 * what `error_message()` (backend/api/deps.py) returns VERBATIM for a
 * ValidationError that slips past this app's own client-side checks (see
 * schema/numberValidity.ts's hasNumberOutOfRange docstring for why that
 * should be rare but not zero -- it can't see every server-side rule, e.g.
 * breaker_box's start_value/numbering_scheme cross-field parity check) --
 * into one readable "<field>: <message>" line (or several, "; "-joined).
 * Verified against a live 422 body:
 *
 *   "1 validation error for BreakerBoxParams\npitch_mm\n  Input should be
 *   greater than or equal to 10 [type=greater_than_equal, input_value=5,
 *   input_type=int]\n    For further information visit
 *   https://errors.pydantic.dev/2.13/v/greater_than_equal"
 *   -> "pitch_mm: Input should be greater than or equal to 10"
 *
 * Returns null for anything that doesn't start with pydantic's own header,
 * so a genuinely different (already-readable) string message passes
 * through extractErrorDetail below unchanged. */
export function parsePydanticValidationError(detail: string): string | null {
  if (!PYDANTIC_ERROR_HEADER_RE.test(detail)) return null;

  const body = detail.replace(PYDANTIC_ERROR_HEADER_RE, "");
  const messages: string[] = [];
  for (const match of body.matchAll(PYDANTIC_ERROR_BLOCK_RE)) {
    const field = match[1]!.trim();
    const message = match[2]!.trim().replace(/^Value error,\s*/, "");
    messages.push(`${field}: ${message}`);
  }
  return messages.length > 0 ? messages.join("; ") : null;
}

/** Turn a FastAPI error body into one readable line, never a raw JSON dump.
 *
 * FastAPI 422s come in two shapes: our own handlers raise
 * HTTPException(422, detail="a readable string") (router_labels.py /
 * router_print.py's error_message()), but automatic pydantic
 * request-validation failures (e.g. a malformed body) produce
 * `detail: [{loc, msg, type}, ...]` instead. Both are handled here so the
 * UI never has to know which one it got -- and a "readable string" can
 * ITSELF be a raw pydantic ValidationError dump (error_message() returns
 * `str(exc)` unmodified for that exception type), so every string detail
 * is run through parsePydanticValidationError first. */
export function extractErrorDetail(body: unknown, fallback: string): string {
  if (body === null || typeof body !== "object") return fallback;
  const detail = (body as ApiErrorBody).detail;
  if (typeof detail === "string" && detail.trim() !== "") {
    return parsePydanticValidationError(detail) ?? detail;
  }
  if (isValidationIssueArray(detail) && detail.length > 0) {
    return detail
      .map((issue) => {
        const loc = issue.loc.filter((part) => part !== "body").join(".");
        return loc ? `${loc}: ${issue.msg}` : issue.msg;
      })
      .join("; ");
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // `...init` spreads FIRST so the computed `headers` below always wins --
  // reversed, an `init.headers` key (even `undefined`, which every call
  // site above implicitly has by omitting it) would silently clobber the
  // Content-Type merge, since a later object-literal key always overrides
  // an earlier one of the same name.
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: init?.body !== undefined ? { "Content-Type": "application/json", ...init.headers } : init?.headers,
  });

  if (!res.ok) {
    const fallback = `request failed: ${res.status} ${res.statusText}`;
    let detail = fallback;
    try {
      const body: unknown = await res.json();
      detail = extractErrorDetail(body, fallback);
    } catch {
      // non-JSON error body (network layer, proxy, etc.) -- keep the fallback.
    }
    throw new ApiError(res.status, detail);
  }

  return (await res.json()) as T;
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}

export function getLabelTypes(): Promise<LabelTypeInfo[]> {
  return request<LabelTypeInfo[]>("/label-types");
}

export function getFonts(): Promise<FontInfo[]> {
  return request<FontInfo[]>("/fonts");
}

export function getTapes(): Promise<TapeInfo[]> {
  return request<TapeInfo[]>("/tapes");
}

export function getSymbols(): Promise<SymbolInfo[]> {
  return request<SymbolInfo[]>("/symbols");
}

/** GET /api/symbols/{id} serves raw SVG bytes (not JSON) -- callers set an
 * <img src> to this URL directly rather than fetching it through here. */
export function symbolSvgUrl(symbolId: string): string {
  return `${API_BASE}/symbols/${symbolId}`;
}

/** POST /api/images (multipart upload, task 2.7) -- bypasses request()'s
 * JSON Content-Type (the browser sets multipart/form-data's own boundary
 * automatically; setting Content-Type by hand would drop it). */
export async function postImage(file: File): Promise<ImageUploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/images`, { method: "POST", body: form });
  if (!res.ok) {
    const fallback = `image upload failed: ${res.status} ${res.statusText}`;
    let detail = fallback;
    try {
      detail = extractErrorDetail(await res.json(), fallback);
    } catch {
      // non-JSON error body -- keep the fallback.
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as ImageUploadResponse;
}

/** GET /api/images/{id} serves raw PNG bytes -- an <img src> URL, same
 * convention as symbolSvgUrl above. */
export function imagePngUrl(imageId: string): string {
  return `${API_BASE}/images/${imageId}`;
}

export function postPreview(body: PreviewRequest): Promise<PreviewResponse> {
  return request<PreviewResponse>("/render/preview", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function postPrint(body: PrintRequest): Promise<PrintJobResponse> {
  return request<PrintJobResponse>("/print", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** POST /api/print/estimate (task 2.9): the SAME body postPrint() accepts,
 * returning a tape-usage estimate WITHOUT creating a job -- what the
 * JobTray calls before committing to an actual print. */
export function postPrintEstimate(body: PrintRequest): Promise<PrintEstimateResponse> {
  return request<PrintEstimateResponse>("/print/estimate", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getPrintJob(jobId: string): Promise<PrintJob> {
  return request<PrintJob>(`/print/jobs/${jobId}`);
}

export function getPrinterStatus(): Promise<PrinterStatusResponse> {
  return request<PrinterStatusResponse>("/printer/status");
}

/** data: URL for a base64 PNG payload, as returned by /api/render/preview
 * (png_b64) or a print job's thumbnail_png_b64. */
export function pngDataUrl(pngB64: string): string {
  return `data:image/png;base64,${pngB64}`;
}
