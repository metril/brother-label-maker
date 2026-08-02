import type {
  ApiErrorBody,
  AuthMe,
  CsvUploadResponse,
  ExpandRequest,
  ExpandResponse,
  FontInfo,
  GalleryItem,
  HealthResponse,
  HistoryJob,
  HistoryListParams,
  HistoryListResponse,
  HomeboxEntityPage,
  HomeboxEntitySummary,
  HomeboxPathSegment,
  HomeboxSettings,
  HomeboxSettingsUpdate,
  HomeboxStatus,
  HomeboxTreeItem,
  ImageUploadResponse,
  LabelTypeInfo,
  Preset,
  PresetCreateRequest,
  PresetPrintRequest,
  PresetUpdateRequest,
  PreviewRequest,
  PreviewResponse,
  PrintEstimateResponse,
  PrintJob,
  PrintJobResponse,
  PrintRequest,
  PrinterStatusResponse,
  ReprintResponse,
  SettingsResponse,
  SettingsUpdate,
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

/** Strips pydantic v2's own "Value error, " prefix -- added automatically
 * whenever a `@field_validator`/`@model_validator` raises a plain
 * `ValueError` (e.g. Sequence's total-labels-cap check, backend/render/
 * serialize.py) -- from a single message. Shared by
 * parsePydanticValidationError's block regex below (the STRING-dump shape
 * a route's own error_message() produces) AND extractErrorDetail's array
 * branch (FastAPI's own AUTOMATIC request-validation shape, `detail: [
 * {loc, msg, type}]` -- what a body-level model_validator failure that
 * NO route ever catches, like the one above, actually arrives as) -- a
 * `ValueError` message reads the same, readable way regardless of which
 * of the two shapes it happens to surface in. Review fix-up: the array
 * branch used to skip this entirely, leaking "Value error, " verbatim
 * into the over-cap message shown in the Serialize panel. */
function stripValueErrorPrefix(message: string): string {
  return message.replace(/^Value error,\s*/, "");
}

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
    const message = stripValueErrorPrefix(match[2]!.trim());
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
        const msg = stripValueErrorPrefix(issue.msg);
        return loc ? `${loc}: ${msg}` : msg;
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

  // task 2.13: DELETE /api/presets/{id} and DELETE /api/history/{id} both
  // respond 204 No Content (router_presets.py/router_history.py) -- no
  // earlier caller of request() ever hit a 204 before this task, so
  // `await res.json()` unconditionally would throw on the empty body.
  if (res.status === 204) {
    return undefined as T;
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

/** POST /api/print/jobs/{id}/cancel (task 2.9's CAS contract, task 2.12's
 * UI): 200 with `{status: "canceled"}` only when the job was still queued
 * at the moment the server processed this request; 409 (a readable message
 * naming the job's real current status, e.g. "cannot cancel job in status
 * 'printing'") once the worker has already dequeued it; 404 for an unknown
 * id. The 409/404 message comes back through exactly the same ApiError/
 * extractErrorDetail path as every other endpoint -- see hooks/
 * usePrintJob.ts, which is the only caller. */
export function postCancelPrintJob(jobId: string): Promise<{ status: string }> {
  return request<{ status: string }>(`/print/jobs/${jobId}/cancel`, { method: "POST" });
}

/** POST /api/render/expand (task 2.11): the distinct values a Sequence
 * produces (and, with `sample`, those values substituted for `{seq}`/
 * `{csv.<col>}` in a template string) -- see hooks/useSequenceExpand.ts,
 * which drives the Serialize panel's live value chips and total-labels
 * readout from this. */
export function postExpand(body: ExpandRequest): Promise<ExpandResponse> {
  return request<ExpandResponse>("/render/expand", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** POST /api/serialize/csv (multipart upload, task 2.11) -- same bypass-
 * request()'s-JSON-Content-Type pattern as postImage above (the browser
 * sets multipart/form-data's own boundary automatically). Stateless: the
 * response's `rows` is posted straight back as a Sequence's own `rows`
 * field, never persisted server-side. */
export async function postSerializeCsv(file: File): Promise<CsvUploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/serialize/csv`, { method: "POST", body: form });
  if (!res.ok) {
    const fallback = `CSV upload failed: ${res.status} ${res.statusText}`;
    let detail = fallback;
    try {
      detail = extractErrorDetail(await res.json(), fallback);
    } catch {
      // non-JSON error body -- keep the fallback.
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as CsvUploadResponse;
}

export function getPrinterStatus(): Promise<PrinterStatusResponse> {
  return request<PrinterStatusResponse>("/printer/status");
}

/** data: URL for a base64 PNG payload, as returned by /api/render/preview
 * (png_b64) or a print job's thumbnail_png_b64. */
export function pngDataUrl(pngB64: string): string {
  return `data:image/png;base64,${pngB64}`;
}

// --- Presets (task 2.13) ------------------------------------------------

/** GET /api/presets?label_type=&q= -- both filters are optional and combine
 * with AND server-side (db.list_presets). Already sorted favorite-first,
 * then most-recently-updated (see that function's own ORDER BY) -- the
 * Presets page renders this order as-is. */
export function getPresets(params: { label_type?: string; q?: string } = {}): Promise<Preset[]> {
  const search = new URLSearchParams();
  if (params.label_type) search.set("label_type", params.label_type);
  if (params.q) search.set("q", params.q);
  const qs = search.toString();
  return request<Preset[]>(`/presets${qs ? `?${qs}` : ""}`);
}

export function postPreset(body: PresetCreateRequest): Promise<Preset> {
  return request<Preset>("/presets", { method: "POST", body: JSON.stringify(body) });
}

/** PUT /api/presets/{id} -- a true partial update; only send the fields
 * that actually changed (an omitted field is left untouched server-side,
 * see api/router_presets.py's PresetUpdate docstring). */
export function putPreset(id: string, body: PresetUpdateRequest): Promise<Preset> {
  return request<Preset>(`/presets/${id}`, { method: "PUT", body: JSON.stringify(body) });
}

export function deletePreset(id: string): Promise<void> {
  return request<void>(`/presets/${id}`, { method: "DELETE" });
}

/** POST /api/presets/{id}/print -- `body` may be omitted entirely (every
 * field of PresetPrintRequest is itself optional server-side); passing
 * `undefined` here sends no request body at all (matches request()'s own
 * "no Content-Type when body is undefined" branch), not an empty `{}`. */
export function postPresetPrint(id: string, body?: PresetPrintRequest): Promise<PrintJobResponse> {
  return request<PrintJobResponse>(`/presets/${id}/print`, {
    method: "POST",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

// --- History (task 2.13) -------------------------------------------------

export function getHistory(params: HistoryListParams = {}): Promise<HistoryListResponse> {
  const search = new URLSearchParams();
  if (params.page !== undefined) search.set("page", String(params.page));
  if (params.page_size !== undefined) search.set("page_size", String(params.page_size));
  if (params.status) search.set("status", params.status);
  if (params.q) search.set("q", params.q);
  const qs = search.toString();
  return request<HistoryListResponse>(`/history${qs ? `?${qs}` : ""}`);
}

/** GET /api/history/{id} -- the FULL job resource (definition included),
 * unlike GET /api/history's own deliberately light list items. */
export function getHistoryJob(id: string): Promise<HistoryJob> {
  return request<HistoryJob>(`/history/${id}`);
}

export function postHistoryReprint(id: string): Promise<ReprintResponse> {
  return request<ReprintResponse>(`/history/${id}/reprint`, { method: "POST" });
}

export function deleteHistoryJob(id: string): Promise<void> {
  return request<void>(`/history/${id}`, { method: "DELETE" });
}

// --- Gallery (task 2.14) ------------------------------------------------

/** GET /api/gallery -- the curated all-types example catalogue, rendered
 * server-side through the exact /api/render/preview pipeline and cached
 * in-process there (cheap after the first call). */
export function getGallery(): Promise<GalleryItem[]> {
  return request<GalleryItem[]>("/gallery");
}

// --- HomeBox (task 3.4) --------------------------------------------------
// Mirrors backend/api/router_homebox.py. The browser never talks to
// HomeBox directly -- every one of these is a proxied, read-only GET (plus
// PUT .../settings, this app's OWN setting, not HomeBox's).

/** GET /api/homebox/status -- always 200; see HomeboxStatus's own doc. */
export function getHomeboxStatus(): Promise<HomeboxStatus> {
  return request<HomeboxStatus>("/homebox/status");
}

export interface HomeboxEntitiesParams {
  q?: string;
  page?: number;
  page_size?: number;
  parent_id?: string;
}

/** GET /api/homebox/entities -- `q` and `parent_id` combine server-side
 * (see router_homebox.py's list_entities); 503 while unconfigured, 502 for
 * a genuine HomeBox-side problem (both surface through ApiError same as
 * every other route). */
export function getHomeboxEntities(params: HomeboxEntitiesParams = {}): Promise<HomeboxEntityPage> {
  const search = new URLSearchParams();
  if (params.q) search.set("q", params.q);
  if (params.page !== undefined) search.set("page", String(params.page));
  if (params.page_size !== undefined) search.set("page_size", String(params.page_size));
  if (params.parent_id) search.set("parent_id", params.parent_id);
  const qs = search.toString();
  return request<HomeboxEntityPage>(`/homebox/entities${qs ? `?${qs}` : ""}`);
}

/** GET /api/homebox/entities/tree -- `with_items` defaults to false (the
 * browse page's own left rail is locations-only; see components/
 * HomeboxLocationTree.tsx, which also filters defensively on `type` itself). */
export function getHomeboxTree(withItems = false): Promise<HomeboxTreeItem[]> {
  return request<HomeboxTreeItem[]>(`/homebox/entities/tree${withItems ? "?with_items=true" : ""}`);
}

/** GET /api/homebox/entities/{id}/path -- root-first ancestor chain,
 * entity itself last (see HomeboxPathSegment's own doc); the "Add to tray"
 * breadcrumb source (lib/homebox.ts's buildBreadcrumb). */
export function getHomeboxEntityPath(id: string): Promise<HomeboxPathSegment[]> {
  return request<HomeboxPathSegment[]>(`/homebox/entities/${encodeURIComponent(id)}/path`);
}

/** GET /api/homebox/assets/{assetId} -- zero, one, or many matches (asset
 * ids are NOT unique); the browse page's own asset-id-jump disambiguation
 * renders all of them as cards for the user to pick from. */
export function getHomeboxAssetMatches(assetId: string): Promise<HomeboxEntitySummary[]> {
  return request<HomeboxEntitySummary[]>(`/homebox/assets/${encodeURIComponent(assetId)}`);
}

/** GET /api/homebox/settings -- `effective_qr_base_url` is what "Add to
 * tray" reads to compose a label's `qr_data` (see lib/homebox.ts's
 * buildHomeboxLabelDefinition); never fabricate a base URL when it's null. */
export function getHomeboxSettings(): Promise<HomeboxSettings> {
  return request<HomeboxSettings>("/homebox/settings");
}

/** PUT /api/homebox/settings (task 4.2's Settings page) -- `qr_base_url:
 * null` clears the stored override back to the config.homebox_url
 * fallback; any 422 (bad scheme, embedded whitespace, over max_length)
 * comes back through the same ApiError/extractErrorDetail path as every
 * other route. */
export function putHomeboxSettings(body: HomeboxSettingsUpdate): Promise<HomeboxSettings> {
  return request<HomeboxSettings>("/homebox/settings", { method: "PUT", body: JSON.stringify(body) });
}

// --- Auth (task 4.1) --------------------------------------------------
// Mirrors backend/api/router_auth.py. Signing IN is a real browser
// navigation, not a fetch: GET /api/auth/login 302s the WHOLE PAGE to the
// IdP, which a fetch() call cannot do (it would follow the redirect
// in-band and hand back the IdP's own login HTML as this app's response
// body) -- so there is deliberately no postAuthLogin() here; AppShell's
// sign-in panel links to it directly via a plain <a href>.

/** GET /api/auth/me -- always 200, in BOTH auth modes; see hooks/useAuth.ts,
 * the only intended caller. */
export function getAuthMe(): Promise<AuthMe> {
  return request<AuthMe>("/auth/me");
}

/** POST /api/auth/logout -- 204/no body. AppShell's sign-out button calls
 * this and then reloads the page, rather than hand-resetting every piece
 * of client-side state (query cache, zustand stores) itself. */
export function postAuthLogout(): Promise<void> {
  return request<void>("/auth/logout", { method: "POST" });
}

// --- Settings (task 4.5) -------------------------------------------------

/** GET /api/settings -- every editable (DB-overlay) row plus a handful of
 * read-only, informational ones (see api/types.ts's SettingRow doc for the
 * exact shape). */
export function getSettings(): Promise<SettingsResponse> {
  return request<SettingsResponse>("/settings");
}

/** PUT /api/settings -- a true partial update (an omitted field is left
 * untouched server-side; `null` reverts that field to its env/default
 * value). Returns the SAME shape GET does, already reflecting the change
 * (including any homebox client rebuild server-side) -- callers should
 * write the response straight into the ["settings"] query cache rather
 * than refetching. */
export function putSettings(partial: SettingsUpdate): Promise<SettingsResponse> {
  return request<SettingsResponse>("/settings", { method: "PUT", body: JSON.stringify(partial) });
}
