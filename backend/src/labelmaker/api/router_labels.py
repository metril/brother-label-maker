"""GET /api/label-types, GET /api/fonts, GET /api/tapes, GET /api/symbols,
GET /api/symbols/{id}, POST /api/render/preview, POST /api/render/expand,
POST /api/serialize/csv.

Preview and print are the same bitmap (see labelmaker.render's module
docstring) -- /render/preview runs the exact same render_definition ->
rasterize -> preview_png pipeline the print worker will later run for the
same definition, just synchronously and without persisting a job. It's
given the app's `data_dir` (task 2.7) so a "text" label whose `icon` is
`{kind: "image", ...}` can resolve the uploaded file the same way the print
worker eventually will -- see render/types/text_label.py's module docstring.
/render/expand and /serialize/csv (task 2.4) are pure data-shaping
endpoints in support of BarTender-model serialization -- neither one
renders anything; see labelmaker.render.serialize's module docstring for
the expansion model itself.

GET /api/symbols / GET /api/symbols/{id} (task 2.7, expanded to 8000+ icons
across Material Symbols, Phosphor and five more sources by commit 7's
symbols pipeline) expose render/symbols.py's curated icon library -- the
catalog and one icon's raw SVG, respectively -- for a UI icon picker and for
symbol_object() ids to be discoverable independent of this project's own
source tree. Both routes are conditional-GET-aware (weak ETag, plus
Last-Modified on the per-icon route) and cache-control'd: GET /api/symbols
returns render/symbols.py's pre-encoded, mtime-cached response bytes rather
than paying a deep-copy + re-encode of 8362 models per request (H4,
docs/code-review-2026-08.md), and both carry `Cache-Control` so a browser
that already has a fresh copy can skip the transfer entirely, or at worst
revalidate with a 304 (H5, same doc). Neither Cache-Control uses
`immutable`/a year-long max-age: catalog and per-icon content can both
change out from under a stable id when the symbols pipeline regenerates, so
revalidation must stay meaningful, not just present.
"""

from __future__ import annotations

import base64
import csv
import io
from email.utils import formatdate
from pathlib import Path

import anyio
from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel, Field

from labelmaker.api.deps import AppConfigDep, error_message
from labelmaker.api.router_images import _read_capped
from labelmaker.driver.geometry import MIN_FEED_MM, all_tapes, dots_to_mm
from labelmaker.render import (
    FontInfo,
    list_fonts,
    list_types,
    preview_png,
    rasterize,
    render_definition,
)
from labelmaker.render.document import LabelDefinition, RenderWarning, family_name
from labelmaker.render.serialize import (
    MAX_CSV_ROWS,
    Sequence,
    distinct_pairs,
    expand_definition,
    expand_tokens,
    ordered_values,
    sequence_values,
    total_labels,
)
from labelmaker.render.symbols import (
    get_symbol_info,
    list_symbols_json,
    resolve_symbol_path,
    symbols_etag,
    validate_symbol_svg,
)

# Shared cache-control policy for both symbol routes (H5): long enough to
# skip most repeat transfers, short of `immutable`/a year -- the symbols
# pipeline can regenerate a given id's content (see H3's fix, running
# alongside this one) or the whole catalog, so a client must keep checking
# back rather than trusting the response forever. Both routes also set a
# weak ETag so that "checking back" is a cheap 304, not a re-download.
_SYMBOLS_CACHE_CONTROL = "public, max-age=86400"

router = APIRouter(tags=["labels"])

# /render/expand's `samples` cap ("first 24 max, for UI chips" -- brief).
_MAX_SAMPLES = 24


@router.get("/label-types")
async def get_label_types() -> list[dict]:
    # Every LabelTypeInfo field (type/title/category/min_tape_mm/params_schema)
    # passes through as-is -- no per-field allowlist to keep in sync when
    # base.py's LabelTypeInfo shape grows (e.g. category/min_tape_mm, task 2.2).
    return [info.model_dump() for info in list_types()]


@router.get("/fonts")
async def get_fonts() -> list[FontInfo]:
    return list_fonts()


class TapeInfo(BaseModel):
    """GET /api/tapes' shape for one geometry.TapeSpec -- the API-facing
    view of tape geometry, kept separate from TapeSpec itself (which also
    carries driver-only fields like status_width_mm that no client needs)."""

    nominal_mm: float
    family: str
    print_dots: int
    print_mm: float
    max_length_mm: float


@router.get("/tapes")
async def get_tapes() -> list[TapeInfo]:
    return [
        TapeInfo(
            nominal_mm=tape.nominal_mm,
            family=family_name(tape.family),
            print_dots=tape.print_dots,
            print_mm=round(dots_to_mm(tape.print_dots), 1),
            max_length_mm=tape.max_length_mm,
        )
        for tape in all_tapes()
    ]


def _etag_matches(if_none_match: str | None, etag: str) -> bool:
    """True if `etag` satisfies an `If-None-Match` request header -- either
    the `*` wildcard or a literal match among its comma-separated values
    (RFC 7232 3.2). Every ETag this API issues is weak (`W/"..."`), so a
    plain string-membership check is a correct weak comparison (RFC 7232
    2.1's weak-comparison rule: equal after stripping the `W/` prefix,
    which two weak tags produced from the same `f'W/"{mtime_ns}"'` format
    already are without stripping anything).
    """
    if if_none_match is None:
        return False
    if if_none_match.strip() == "*":
        return True
    candidates = {part.strip() for part in if_none_match.split(",")}
    return etag in candidates


@router.get("/symbols")
async def get_symbols(request: Request) -> Response:
    # H4: list_symbols_json() is the pre-encoded-bytes cache (see its
    # docstring) -- no per-request deep copy, no per-request
    # jsonable_encoder/response-model pass. H5: ETag + Cache-Control, with
    # a matching If-None-Match short-circuiting to 304 before touching the
    # (possibly still-uncached) bytes at all.
    etag = symbols_etag()
    headers = {"ETag": etag, "Cache-Control": _SYMBOLS_CACHE_CONTROL}
    if _etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    return Response(content=list_symbols_json(), media_type="application/json", headers=headers)


@router.get("/symbols/{symbol_id}")
async def get_symbol_svg(symbol_id: str, request: Request) -> Response:
    try:
        info = get_symbol_info(symbol_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=error_message(exc)) from exc
    # L9 (2026-08 review): resolve-and-contain the manifest-supplied path
    # (mirrors render/images.py's image_path() for uploads) instead of an
    # unchecked SYMBOLS_DIR / info.path join -- a regex-valid-shaped id
    # whose manifest entry nonetheless resolves outside SYMBOLS_DIR (a bad
    # entry, or a symlink surprise) 404s here rather than escaping as a
    # raw 500 or serving something unintended.
    try:
        path = resolve_symbol_path(info)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=error_message(exc)) from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"symbol file missing: {info.path}")
    # H5: ETag + Last-Modified from the FILE (not index.json -- a symbol's
    # svg can be regenerated by the pipeline without index.json itself
    # changing), same weak-etag format and cache-control policy as
    # GET /api/symbols above (see _SYMBOLS_CACHE_CONTROL's comment for why
    # neither route uses `immutable`). X-Content-Type-Options (L9): this
    # route serves raw SVG -- script-executing active content when
    # navigated to directly -- from the app's own origin; nosniff is
    # defense in depth alongside the content validation below, not a
    # substitute for it.
    stat = path.stat()
    etag = f'W/"{stat.st_mtime_ns}"'
    headers = {
        "ETag": etag,
        "Last-Modified": formatdate(stat.st_mtime, usegmt=True),
        "Cache-Control": _SYMBOLS_CACHE_CONTROL,
        "X-Content-Type-Options": "nosniff",
    }
    if _etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)

    raw = path.read_bytes()
    # L9: validate BEFORE serving as active image/svg+xml content -- a
    # future hostile/malformed catalog entry (a <script> sibling, an
    # event-handler attribute, a href/xlink:href) is rejected the same way
    # a curation mistake already is at render time
    # (symbol_object() -> _validate_symbol_svg()), never served verbatim.
    # Validated per request (files are small, see render/symbols.py's own
    # docstring on catalog size) rather than once at load time, so this
    # stays correct even if the pipeline regenerates a file's content
    # without index.json's mtime changing.
    try:
        text = raw.decode("utf-8")
        validate_symbol_svg(info, text)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=404, detail=f"symbol {symbol_id!r} failed content validation"
        ) from exc
    return Response(content=raw, media_type="image/svg+xml", headers=headers)


class PreviewRequest(BaseModel):
    definition: LabelDefinition
    scale: int = Field(default=2, ge=1, le=8)
    # task 2.4: when set, `definition` is treated as the TEMPLATE and
    # `index` selects which of serialization's expanded labels to render
    # (see expand_definition) -- mirrors POST /api/print's template +
    # serialization split (router_print.py), so a caller can preview any
    # instance of a serialized run before committing to a print job.
    serialization: Sequence | None = None
    index: int = Field(default=0, ge=0)


def _render_and_encode(
    definition: LabelDefinition,
    scale: int,
    serialization: Sequence | None,
    index: int,
    data_dir: Path,
) -> dict:
    total_labels_: int | None = None
    sequence_value: str | None = None
    target = definition

    if serialization is not None:
        bound = expand_definition(definition.model_dump(mode="json"), serialization)
        total_labels_ = len(bound)
        if index >= total_labels_:
            raise ValueError(f"index {index} is out of range for {total_labels_} label(s)")
        sequence_value = ordered_values(serialization)[index]
        target = LabelDefinition.model_validate(bound[index])

    rendered = render_definition(target, data_dir=data_dir)
    img: Image.Image = rasterize(rendered)
    png_bytes = preview_png(img, scale=scale)
    length_mm_raw = dots_to_mm(rendered.width_px)

    # task 2.9: a heads-up that this label is under the mechanical
    # head-to-cutter feed constant (MIN_FEED_MM), surfaced here too
    # (SIMPLER option the brief chose over a full TapeEstimate on preview,
    # since chain_mode isn't known yet at preview time -- the full,
    # mode-aware estimate is POST /api/print/estimate's job, see
    # router_print.py; render.estimate.estimate() does NOT treat
    # MIN_FEED_MM as a floor for cut_each -- see that module's docstring --
    # so this warning deliberately says "at least", not "exactly", to avoid
    # implying a number that endpoint won't actually return). `short_label`
    # is appended to `warnings` (not a separate bool) so the frontend's
    # existing warning-chip rendering picks it up automatically -- compared
    # against the UNROUNDED length so a value that only LOOKS >= the
    # constant after rounding to 1 decimal still gets flagged correctly.
    warnings = list(rendered.warnings)
    if length_mm_raw < MIN_FEED_MM:
        warnings.append(
            RenderWarning(
                code="short_label",
                severity="info",
                message=(
                    f"this label is {round(length_mm_raw, 1):g}mm long; the printer's "
                    f"minimum feed is {MIN_FEED_MM:g}mm, so it will consume at least "
                    f"{MIN_FEED_MM:g}mm of tape (see /api/print/estimate for the full "
                    "job estimate)."
                ),
            )
        )

    return {
        "png_b64": base64.b64encode(png_bytes).decode("ascii"),
        # SCALED png dimensions (device dots x scale) -- named png_* so the
        # unit trap is visible at the field name itself: never derive mm
        # from these, always read length_mm below (see api/types.ts's
        # PreviewResponse doc on the frontend side of this contract).
        "png_width_px": img.width * scale,
        "png_height_px": img.height * scale,
        "length_mm": round(length_mm_raw, 1),
        "min_feed_mm": MIN_FEED_MM,
        "warnings": warnings,
        "total_labels": total_labels_,
        "sequence_value": sequence_value,
    }


@router.post("/render/preview")
async def render_preview(body: PreviewRequest, config: AppConfigDep) -> dict:
    try:
        return await anyio.to_thread.run_sync(
            _render_and_encode,
            body.definition,
            body.scale,
            body.serialization,
            body.index,
            config.data_dir,
        )
    except (KeyError, ValueError) as exc:
        # ValueError also catches pydantic.ValidationError (a subclass) from
        # renderer.Params.model_validate() inside render_definition -- an
        # invalid `params` payload for the chosen label type surfaces here
        # the same way an unknown type/tape does. Also covers
        # expand_definition's own ValueErrors (ALPHA under/overflow,
        # unknown {csv.<col>}) and the out-of-range `index` check above.
        raise HTTPException(status_code=422, detail=error_message(exc)) from exc


class ExpandRequest(BaseModel):
    serialization: Sequence
    sample: str | None = None


def _expand_preview(serialization: Sequence, sample: str | None) -> dict:
    result: dict = {
        "values": sequence_values(serialization),
        "total_labels": total_labels(serialization),
        "samples": None,
    }
    if sample is not None:
        # Distinct values only (NOT the copies_per_value-multiplied,
        # collated run expand_definition produces) -- these are "what does
        # each distinct value look like substituted in", for UI chips, not
        # a preview of the full print run. Capped at _MAX_SAMPLES
        # regardless of how many distinct values there are.
        result["samples"] = [
            expand_tokens(sample, value, row)
            for value, row in distinct_pairs(serialization)[:_MAX_SAMPLES]
        ]
    return result


@router.post("/render/expand")
async def expand_sequence(body: ExpandRequest) -> dict:
    try:
        return _expand_preview(body.serialization, body.sample)
    except (KeyError, ValueError) as exc:
        # ValueError covers ALPHA under/overflow (sequence_values) and an
        # unknown {csv.<col>} in `sample` (expand_tokens) -- Sequence's own
        # structural constraints (bad kind-specific requirements, the
        # total-labels cap, etc.) already 422 automatically via FastAPI's
        # request-body validation before this handler even runs.
        raise HTTPException(status_code=422, detail=error_message(exc)) from exc


MAX_CSV_UPLOAD_BYTES = 1024 * 1024  # 1 MiB


@router.post("/serialize/csv")
async def upload_serialize_csv(request: Request, file: UploadFile) -> dict:
    """Stateless CSV echo for task 2.4's CSV-kind Sequence: parses an
    uploaded CSV with stdlib `csv`, into the same {columns, rows, row_count}
    shape the frontend (2.11) turns around and posts back as
    Sequence(kind=csv, rows=...). Nothing is persisted here -- the frontend
    holds the parsed rows client-side until the user submits a print/preview
    request that embeds them.
    """
    raw = await _read_capped(request, file, max_bytes=MAX_CSV_UPLOAD_BYTES, status_code=413)
    # Decode + csv parse is CPU-bound; keep it off the event loop.
    return await anyio.to_thread.run_sync(_parse_csv_upload, raw)


def _parse_csv_upload(raw: bytes) -> dict:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"CSV file is not valid UTF-8: {exc}") from exc

    reader = csv.reader(io.StringIO(text))
    try:
        header = [column.strip() for column in next(reader)]
    except StopIteration:
        raise HTTPException(status_code=422, detail="CSV file is empty") from None
    if not header or any(column == "" for column in header):
        raise HTTPException(
            status_code=422, detail="CSV header row must have non-empty column names"
        )

    seen: set[str] = set()
    duplicates: set[str] = set()
    for column in header:
        if column in seen:
            duplicates.add(column)
        seen.add(column)
    if duplicates:
        raise HTTPException(
            status_code=422, detail=f"duplicate CSV column(s): {sorted(duplicates)}"
        )

    rows: list[dict[str, str]] = []
    for line_no, raw_row in enumerate(reader, start=2):
        if not raw_row:  # a genuinely blank line -- not a ragged row
            continue
        if len(rows) >= MAX_CSV_ROWS:
            # Bail as soon as row MAX_CSV_ROWS+1 is READ -- before
            # validating or appending it, and long before `reader` would
            # otherwise be drained to the end of the file. A large-enough
            # upload (millions of rows) would otherwise balloon RSS well
            # past the file's own size while `rows` grows unbounded, only
            # to be rejected anyway once every row had already been
            # parsed and appended.
            raise HTTPException(
                status_code=422, detail=f"CSV file has more than {MAX_CSV_ROWS} data rows"
            )
        if len(raw_row) != len(header):
            raise HTTPException(
                status_code=422,
                detail=(f"CSV row {line_no} has {len(raw_row)} column(s), expected {len(header)}"),
            )
        # Row values stripped the same way header column names are above --
        # untrimmed whitespace around a CSV cell (common from spreadsheet
        # exports) shouldn't become part of e.g. a {csv.port} substitution.
        rows.append(dict(zip(header, (value.strip() for value in raw_row), strict=True)))

    if not rows:
        raise HTTPException(status_code=422, detail="CSV file has no data rows")

    return {"columns": header, "rows": rows, "row_count": len(rows)}
