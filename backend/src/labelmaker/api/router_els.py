"""GET /api/els/label (task 3.5): HomeBox's External Label Service (ELS).

-- What ELS is --

HomeBox has an extension point: setting `HBOX_LABEL_MAKER_LABEL_SERVICE_URL`
on the HomeBox server makes it delegate ALL of its own label PNG rendering
(the "print label" button on an item/location/asset page) to an external
HTTP service, fetched with a plain unauthenticated `GET` carrying
`User-Agent: Homebox-LabelMaker/1.0`. This router IS that external service --
mounted at whatever path an operator points `HBOX_LABEL_MAKER_LABEL_SERVICE_URL`
at (HomeBox appends its query string to whatever URL it's given; it has no
opinion about the path shape at all -- see the contract below).

-- The pinned contract --

Verified against HomeBox's OWN source, not the third-party reference
service (per this task's own instruction: "if the two sources disagree,
HomeBox's own source wins") -- fetched 2026-07-28 from
`sysadminsmedia/homebox` @ `main`:

  - `backend/pkgs/labelmaker/labelmaker.go`, `fetchLabelFromURL()`: builds
    the outbound request HomeBox itself makes to `LabelServiceUrl`. This is
    the definitive wire contract -- every query param below, its type, and
    whether it's always sent all come from this function's `query.Set(...)`
    calls.
  - `backend/app/api/handlers/v1/v1_ctrl_labelmaker.go`: the THREE callers
    (`HandleGetLocationLabel` / `HandleGetItemLabel` / `HandleGetAssetLabel`)
    that build `title`/`description`/`url` before handing them to
    `labelmaker.NewGenerateParams(...)` -- this is what pins down what
    `TitleText`/`DescriptionText`/`URL` actually CONTAIN in practice, since
    the query-param names alone don't say that.

Cross-checked against the reference implementation's own README
(`Robert27/homebox-label-service` -- now archived/renamed to
`roberteggl/homebox-label-service`, fetched 2026-07-28) -- it agrees on
every param name/type and independently documents `DynamicLength` as
"accepted but ignored", which HomeBox's own source corroborates (see below).
No disagreement was found between the two sources.

Query params HomeBox ALWAYS sends (unconditional `query.Set(...)` calls in
`fetchLabelFromURL`):

  - `Width` (int), `Height` (int), `Margin` (int), `ComponentPadding` (int),
    `TitleFontSize` (float, Go `%f` format e.g. "32.000000"),
    `DescriptionFontSize` (float), `Dpi` (float, ALWAYS "72.000000" --
    `labelmaker.NewGenerateParams` hardcodes `Dpi: 72`, it is not actually
    configurable despite being a query param), `QrSize` (int, `=
    Height - 2*ComponentPadding`), `DynamicLength` (bool, Go `%t` ->
    "true"/"false").

    ALL of the above describe HomeBox's OWN internal (non-delegated)
    generator's canvas at 72dpi and are IGNORED here: `fetchLabelFromURL`
    does not check the fetched image's dimensions against them at all (it
    just streams the response body through), so nothing this endpoint
    returns is compared against them. This app has its own tape geometry
    (180dpi, a fixed set of physical tape widths) that HomeBox has no
    concept of, so honoring 72dpi pixel math here would be actively wrong --
    see `AppConfig.els_tape_mm`'s own docstring for what actually decides
    this endpoint's output geometry instead. Accepted as typed (but unused)
    query params anyway, purely so a malformed value from a non-conforming
    caller still 422s cleanly rather than being silently swallowed.

  - `TitleText` (str): the ONE field guaranteed non-empty in every one of
    HomeBox's three callers -- `location.Name`, `item.Name`, or
    `item.AssetID.String()` respectively. Mapped to `homebox_location`'s
    `name` (see mapping rationale below).
  - `DescriptionText` (str): built differently per caller and can
    legitimately be EMPTY (`HandleGetItemLabel` starts it at `""` and only
    appends `"\nLocation: {parent}"` if the item has a parent -- a
    top-level item's `DescriptionText` is exactly `""`). For
    `HandleGetLocationLabel` it's always the literal constant
    `"Homebox Location"`; for `HandleGetAssetLabel` it's
    `"{item.Name}\nLocation: {parent}"` (or just `"{item.Name}"` with no
    parent). Mapped to `homebox_location`'s `path` (see below).
  - `URL` (str): the full label URL HomeBox itself composed --
    `{hbURL}/location/{id}`, `{hbURL}/item/{id}`, or `{hbURL}/a/{assetID}`.
    This is the exact string the QR code must encode. Mapped to `qr_data`.

Query param HomeBox sends ONLY when its own admin configured a fixed value
(`cfg.LabelMaker.AdditionalInformation` -- an instance-wide constant, NOT
per-item, e.g. a domain name shown on every label; unrelated to any
per-item id despite the reference service's README calling it "an ID
value"):

  - `AdditionalInformation` (str, optional): folded into `path` alongside
    `DescriptionText` when present (see below).

-- Render mapping: why `homebox_location`, not `homebox_asset` --

The three HomeBox callers above all funnel through the exact same
`TitleText`/`DescriptionText`/`URL` triple with no discriminator telling
this endpoint which of the three flows produced a given request -- exactly
the "contract is just title/description/QR-url generic" case this task's
brief anticipated, which named `homebox_asset` as the fallback mapping.
Deviation: this module uses `homebox_location` instead, verified deliberately
against BOTH types' actual `Params` field bounds
(render/types/homebox_asset.py, render/types/homebox_location.py):

  - `homebox_asset.Params` requires BOTH `asset_id` (1-32 chars) AND `name`
    (1-120 chars) to be non-empty. This endpoint only has ONE field
    guaranteed non-empty by the contract (`TitleText`) -- `DescriptionText`
    is legitimately `""` for a top-level item's label (see above). Mapping
    `TitleText`/`DescriptionText` onto `asset_id`/`name` would 422 every
    single top-level-item print forever, which is a common, unremarkable
    case, not a malformed request.
  - `homebox_location.Params` requires only `name` (1-120 chars) to be
    non-empty; `path` (0-160 chars) is OPTIONAL and dropped from the label
    entirely when blank (see that module's own docstring). Mapping
    `TitleText -> name` / `DescriptionText (+ AdditionalInformation) ->
    path` handles the always-empty-for-some-callers field correctly with
    no special-casing, at the cost of losing the asset-tag layout's
    dedicated monospace/bold "id" role -- an acceptable trade since HomeBox
    itself renders `TitleText` as one bold, prominent line in its OWN
    layout too (see the reference README's "Layout" section: "Top-left:
    bold title"), which is exactly what `homebox_location`'s bold `name`
    role does.

The mapping:

  - `name` <- `TitleText`, verbatim.
  - `path` <- `DescriptionText` split on embedded newlines (HomeBox's Go
    `\n`-joined multi-line text has no equivalent here -- this package's
    label types render each role as ONE line, see homebox_location.py's own
    docstring -- so newlines are collapsed into a single line), blank lines
    dropped, then `AdditionalInformation` appended if present, all joined
    with " · ". Empty after that (e.g. a top-level item, `DescriptionText
    == ""`, no `AdditionalInformation`) -> `path=""`, which
    `homebox_location`'s own renderer drops from the label entirely.
  - `qr_data` <- `URL`, verbatim.
  - `show_qr` <- always `True`: every one of HomeBox's three callers sends a
    real `URL` (there is no HomeBox flow that omits it), so there's no
    signal that would ever justify a text-only render here.

Field-bound 422s are NOT silently truncated to fit: an over-length
`TitleText`/`DescriptionText` (past `homebox_location.Params`'s own 120/160
char bounds) surfaces as this endpoint's normal 422, exactly like every
other caller of `render_definition` in this codebase already gets for an
over-length field -- see api/deps.py's `error_message`. Silently mangling
data to dodge that felt worse than a clear error an operator can act on
(e.g. by shortening the HomeBox item name).

-- Output geometry: native device pixels, no upscaling --

`AppConfig.els_tape_mm` (default 24.0, tze family, an operator-tunable knob
-- see its own docstring in config.py) picks the ONE physical tape width
every ELS render targets; there's no per-request tape selection in the
contract (HomeBox's `Width`/`Height` describe its own generator, not a tape
choice -- see above). The PNG is rendered at `scale=1` -- literal device
dots at 180dpi, matching this app's own print pipeline (`preview and print
are the same bitmap`, see render/__init__.py's module docstring) -- rather
than upscaled to whatever `Width`/`Height` HomeBox sent, because
`fetchLabelFromURL` never checks the fetched image's dimensions against
those params at all (confirmed above): HomeBox is the one place this PNG
gets consumed as a whole (embedded directly in its own "print label" UI, or
spooled to a temp file for its own `PrintCommand` -- see labelmaker.go's
`PrintLabel`), and neither path enforces a size, so there is nothing to
scale FOR. Rendering native keeps this endpoint on the exact same
`render_definition -> rasterize -> preview_png` pipeline every other route
in this app uses, with no synthetic resampling step invented just for this
one caller.

-- Unrelated to this app's OWN print job pipeline --

Worth flagging explicitly: HomeBox's `PrintLabel` (invoked when its own
"print" checkbox is set) spools the fetched PNG to a temp file and then
executes `cfg.LabelMaker.PrintCommand` -- an arbitrary, HomeBox-admin-
configured OS-level command (e.g. a CUPS `lp` invocation). This is a
COMPLETELY SEPARATE physical-print mechanism from this app's own USB
driver/print-job pipeline (driver/, jobs/worker.py) -- this endpoint only
ever generates the PNG `GenerateLabel` asks for; making HomeBox's own
"print" button actually drive the Brother printer would additionally
require the HomeBox operator to point `HBOX_LABEL_MAKER_PRINT_COMMAND` at
some OS-level sink for that PNG, which is out of scope here (this endpoint
is an image generator, not a print sink).
"""

from __future__ import annotations

import anyio
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from labelmaker.api.deps import AppConfigDep, SettingsDep, error_message
from labelmaker.config import AppConfig
from labelmaker.render import LabelDefinition, Tape, preview_png, rasterize, render_definition
from labelmaker.render.types.homebox_location import HomeboxLocationParams

router = APIRouter(tags=["els"])


def _secondary_text(description_text: str, additional_information: str | None) -> str:
    """`DescriptionText` (HomeBox's own possibly-multi-line, possibly-empty
    secondary text) + an optional admin-configured `AdditionalInformation`
    constant, collapsed to the single line `homebox_location`'s `path` role
    expects (see module docstring's "-- Render mapping --" section).
    """
    lines = [line.strip() for line in description_text.split("\n") if line.strip()]
    if additional_information and additional_information.strip():
        lines.append(additional_information.strip())
    joined = " · ".join(lines)
    # Clamp to homebox_location.path's Field bound (160) rather than 422ing:
    # HomeBox item names alone reach 255 chars and this text is a decorative
    # breadcrumb the renderer already drops entirely when blank -- clipping
    # it can't fail a print, whereas failing the whole label over it turns
    # HomeBox's print button into a broken image (review). TitleText -> name
    # deliberately still fails loudly: mangling the identity field is worse.
    return joined if len(joined) <= 160 else joined[:159] + "…"


@router.get("/els/label")
async def get_els_label(
    config: AppConfigDep,
    settings: SettingsDep,
    # -- Fields this endpoint actually renders (see module docstring's
    # "-- Render mapping --") -- TitleText/URL are the two fields every one
    # of HomeBox's three callers always sends non-empty, so both are
    # required Query params (missing either is a genuine malformed
    # request -> FastAPI's own automatic 422). DescriptionText is
    # legitimately sometimes "" (a top-level item) and so is NOT required.
    title_text: str = Query(..., alias="TitleText", min_length=1, max_length=500),
    description_text: str = Query("", alias="DescriptionText", max_length=2000),
    url: str = Query(..., alias="URL", min_length=1, max_length=2000),
    additional_information: str | None = Query(
        None, alias="AdditionalInformation", max_length=500
    ),
    # -- Fields HomeBox always sends but this endpoint ignores (see module
    # docstring) -- still typed so a non-numeric value 422s cleanly rather
    # than being silently accepted as a string.
    width: int | None = Query(None, alias="Width"),
    height: int | None = Query(None, alias="Height"),
    qr_size: int | None = Query(None, alias="QrSize"),
    margin: int | None = Query(None, alias="Margin"),
    component_padding: int | None = Query(None, alias="ComponentPadding"),
    title_font_size: float | None = Query(None, alias="TitleFontSize"),
    description_font_size: float | None = Query(None, alias="DescriptionFontSize"),
    dpi: float | None = Query(None, alias="Dpi"),
    # Accepted but ignored per the pinned contract (both HomeBox's own
    # source and the reference service's README agree on this one) -- this
    # package's label types are always content-fit width, so there is no
    # "dynamic length" toggle to honor either way.
    dynamic_length: bool = Query(False, alias="DynamicLength"),
) -> Response:
    # task 4.5 Track A: els_enabled is DB-editable (Settings page) now, so
    # main.py registers this route UNCONDITIONALLY -- this per-request check
    # is the only thing left enforcing "disabled -> 404" (never 503; there's
    # no other gate, auth or otherwise, behind this endpoint at all).
    effective = settings.effective()
    if not effective.els_enabled:
        raise HTTPException(status_code=404, detail="not found")

    try:
        params = HomeboxLocationParams(
            name=title_text,
            path=_secondary_text(description_text, additional_information),
            qr_data=url,
        )
        # Same `effective` snapshot as the els_enabled check above, so the
        # tape width used here can't disagree with the flag that just
        # passed.
        els_tape_mm = effective.els_tape_mm
        definition = LabelDefinition(
            type="homebox_location",
            tape=Tape(width_mm=els_tape_mm, family="tze"),
            params=params.model_dump(mode="json"),
        )
        # Off-loop like every other render route (router_labels/router_
        # gallery/the print worker): rasterize is the resvg call, and a
        # burst of HomeBox label-sheet fetches must not stall the event
        # loop that carries /api/ws and the print worker (review).
        png_bytes = await anyio.to_thread.run_sync(_render_png, config, definition)
    except (KeyError, ValueError) as exc:
        # ValueError also catches pydantic.ValidationError (a subclass) --
        # an over-length TitleText, a misconfigured els_tape_mm that doesn't
        # match a real tze tape width, and rasterize/preview_png's own
        # ValueErrors (unbundled font family, bad image mode) all surface
        # here the same readable way every other render_definition caller
        # in this app already gets (api/deps.py's error_message).
        raise HTTPException(status_code=422, detail=error_message(exc)) from exc

    return Response(content=png_bytes, media_type="image/png")


def _render_png(config: AppConfig, definition: LabelDefinition) -> bytes:
    """Synchronous render half, run in a worker thread. scale=1 -- native
    device pixels; see module docstring's "-- Output geometry --" section
    for why nothing here should be upscaled."""
    rendered = render_definition(definition, data_dir=config.data_dir)
    return preview_png(rasterize(rendered), scale=1)
