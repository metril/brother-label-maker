import type {
  ApiErrorBody,
  FontInfo,
  HealthResponse,
  LabelTypeInfo,
  PreviewRequest,
  PreviewResponse,
  PrintEstimateResponse,
  PrintJob,
  PrintJobResponse,
  PrintRequest,
  PrinterStatusResponse,
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

/** Turn a FastAPI error body into one readable line, never a raw JSON dump.
 *
 * FastAPI 422s come in two shapes: our own handlers raise
 * HTTPException(422, detail="a readable string") (router_labels.py /
 * router_print.py's error_message()), but automatic pydantic
 * request-validation failures (e.g. a malformed body) produce
 * `detail: [{loc, msg, type}, ...]` instead. Both are handled here so the
 * UI never has to know which one it got. */
export function extractErrorDetail(body: unknown, fallback: string): string {
  if (body === null || typeof body !== "object") return fallback;
  const detail = (body as ApiErrorBody).detail;
  if (typeof detail === "string" && detail.trim() !== "") return detail;
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
