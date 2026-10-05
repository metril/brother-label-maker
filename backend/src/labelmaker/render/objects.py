"""Barcode "objects": QR / Code128 / Code39 / DataMatrix rendered as pixel-
snapped SVG rect groups, for task 2.5's `barcode` label type (and any future
label type that wants to embed a code inline).

180dpi is marginal for barcodes -- unlike text_label.py/divided_blocks.py's
free-floating glyph coordinates (which resvg antialiases, fine for text),
every module/bar here MUST land on an INTEGER device pixel. A module that
straddles a pixel boundary rasterizes as two partial-intensity pixels
instead of one solid one, and a 1-bit threshold pass (rasterize.py) then
picks ONE side more or less at random -- silently eating or duplicating a
module column, which is not a cosmetic defect for a barcode the way it would
be for a text label: it can make the difference between a scanner reading
the code and not. So every function below builds its whole group from
integer arithmetic only (module_px * an integer module-count), emits plain
integer `<rect>` coordinates (no `_fmt_num`-style decimal formatting, no
`scale()` transform -- resvg is asked to place each rect on the pixel grid
directly), and wraps the group in `shape-rendering="crispEdges"` so resvg
doesn't antialias the (already pixel-aligned) edges anyway.

Every function here returns a BarcodeResult: an SVG `<g>` fragment plus its
own device-pixel width/height (INCLUDING the quiet zone -- the code's own
white margin is part of its footprint, not something a caller adds
separately) and any warnings. Black modules only; the group never paints its
own background (the document-level white background, see document.py's
`_svg_document`, already covers it) -- this also means these groups are
NEVER a dithered ObjectRegion (see document.py's ObjectRegion docstring):
they are pure vector rects, already pre-thresholded by construction (every
pixel they touch is either fully inside a black module or outside all of
them), so the default whole-label "threshold" 1-bit conversion mode is
exactly right for them with nothing extra to declare.

Quiet zones are drawn as part of each function's own width_px/height_px (as
blank space, not literal white rects -- the background is already white),
per each symbology's own convention:
- QR: 4 modules (the ISO/IEC 18004 minimum), each side.
- DataMatrix: 2 modules -- the spec technically only requires 1, but a
  single-module margin at 180dpi (down to 1 physical pixel at module_px=1)
  leaves no room for print-registration slop; 2 is cheap insurance.
- Code128/Code39 (python-barcode's own MIN_QUIET_ZONE convention, adapted to
  our module counting): 10 modules each side.

Code128/Code39 are consumed via python-barcode's `Barcode.build()` -- the
list of 0/1-per-module strings its OWN writers would otherwise turn into
bars -- never its SVGWriter (which emits its own quiet zone/font/text
machinery we don't want; see each function's docstring). QR/DataMatrix are
consumed via their libraries' own module-matrix accessors (`QRCode.
get_matrix()` / `DataMatrix.matrix`), each already a plain list-of-rows of
truthy/falsy modules -- no SVG parsing needed for either (ppf.datamatrix
also offers an `svg()` method, but `.matrix` is the same data one property
access earlier, so there is nothing to gain from parsing its SVG path
instead).
"""

from __future__ import annotations

import string
from collections.abc import Sequence
from typing import NamedTuple

import barcode
import qrcode
from ppf.datamatrix import DataMatrix

from labelmaker.render.document import RenderWarning

# -- quiet zones, per symbology (module counts -- see module docstring) -----
_QR_QUIET_MODULES = 4
_DM_QUIET_MODULES = 2
_BARS_QUIET_MODULES = 10  # each side, Code128 and Code39 alike

# A module/x-dim narrower than this is flagged -- 2px @ 180dpi is ~0.28mm,
# already optimistic for a cheap thermal-tape scan; 1px modules are commonly
# unreadable on real hardware (this is a warning, not a hard cap: the caller
# may still legitimately want the smallest label physically possible and
# accept the risk).
_SMALL_MODULE_PX = 2

# Tallest print head across every tape this project supports (24mm TZe,
# print_dots=128 -- see driver.geometry's tape tables). A square 2D code
# taller than this can never fit ANY tape's print strip, so it's flagged
# regardless of which tape the caller eventually resolves against (objects.py
# itself is tape-agnostic -- it doesn't take a TapeSpec -- so this is a fixed
# constant, not `tape.print_dots`).
_MAX_HEAD_DOTS = 128

_FIT_MAX_MODULE_PX = 20  # qr_fit_group module cap

_QR_ERROR_CORRECTION = qrcode.constants.ERROR_CORRECT_M

# Code39's own charset (ISO/IEC 16388): digits, uppercase A-Z, and
# -. $/+% and space -- exactly python-barcode's own `charsets.code39.REF`
# tuple, duplicated here (rather than imported) so this module's public
# contract doesn't depend on a private submodule path of a third-party
# package; test_objects.py cross-checks the two stay in sync.
CODE39_CHARSET: frozenset[str] = frozenset(string.digits + string.ascii_uppercase + "-. $/+%")


class BarcodeResult(NamedTuple):
    svg_group: str
    width_px: int
    height_px: int
    warnings: list[RenderWarning]


def _rect(x: int, y: int, width: int, height: int) -> str:
    """A filled black rect with plain integer coordinates -- no decimal
    formatting (unlike document.py's `_fmt_num`-based helpers): every
    argument here is already an exact integer (a module/bar count times an
    integer module_px/x_dim_px), and str()-ing an int can never introduce
    the fractional pixel this whole module exists to avoid."""
    return f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="black"/>'


def _group(x: int, y: int, rects: list[str]) -> str:
    """Wrap a list of `_rect(...)` strings in the ONE `<g>` every
    BarcodeResult returns: `transform="translate(x,y)"` (both integers, so
    it composes with the already-integer rect coordinates inside with no
    sub-pixel drift) AND `shape-rendering="crispEdges"` on that SAME
    element -- not two nested groups -- so resvg rasterizes every already
    pixel-aligned edge with no antialiasing softening."""
    return f'<g transform="translate({x},{y})" shape-rendering="crispEdges">{"".join(rects)}</g>'


def _row_rects(matrix: Sequence[Sequence[int]], module_px: int, quiet_modules: int) -> list[str]:
    """One `<rect>` per contiguous horizontal run of "on" modules in each row
    of a 2D module matrix (QR's `get_matrix()` bools or DataMatrix's
    `.matrix` 0/1 ints -- both accepted, truthiness is all that matters),
    offset by `quiet_modules` on both axes. Merging same-row runs into one
    rect (instead of one `<rect>` per module) produces identical pixel
    output -- each run's rect spans exactly the union of its modules' pixel
    cells -- with far fewer SVG elements."""
    rects: list[str] = []
    for row_i, row in enumerate(matrix):
        col = 0
        width = len(row)
        while col < width:
            if not row[col]:
                col += 1
                continue
            start = col
            while col < width and row[col]:
                col += 1
            run_len = col - start
            x = (quiet_modules + start) * module_px
            y = (quiet_modules + row_i) * module_px
            rects.append(_rect(x, y, run_len * module_px, module_px))
    return rects


def _module_runs(module_string: str) -> list[tuple[bool, int]]:
    """Group a python-barcode `Barcode.build()` module string (one char per
    module: '1' = bar, '0' = space) into runs of `(is_bar, width_modules)` --
    the "bar structure" this module consumes instead of the library's own
    SVGWriter. `sum(width for _, width in runs)` always equals
    `len(module_string)` regardless of how runs are grouped; grouping just
    turns N one-module rects into fewer, wider ones for identical pixels."""
    runs: list[tuple[bool, int]] = []
    for ch in module_string:
        is_bar = ch == "1"
        if runs and runs[-1][0] is is_bar:
            runs[-1] = (is_bar, runs[-1][1] + 1)
        else:
            runs.append((is_bar, 1))
    return runs


def _small_module_warning(object_id: str | None, module_px: int, label: str) -> RenderWarning:
    return RenderWarning(
        code="barcode_small_module",
        severity="warning",
        message=(
            f"{label} module size {module_px}px is below the recommended minimum of "
            f"{_SMALL_MODULE_PX}px and may not scan reliably"
        ),
        object_id=object_id,
    )


def _large_barcode_warning(object_id: str | None, size_px: int, label: str) -> RenderWarning:
    return RenderWarning(
        code="barcode_large",
        severity="warning",
        message=(
            f"{label} is {size_px}px, larger than the tallest print head "
            f"({_MAX_HEAD_DOTS}px) -- it will not fit any supported tape"
        ),
        object_id=object_id,
    )


def qr_object(
    data: str, *, module_px: int, x: int = 0, y: int = 0, object_id: str | None = None
) -> BarcodeResult:
    """QR code via `qrcode` (ERROR_CORRECT_M, the usual print-label default
    -- recovers from ~15% damage, a reasonable middle ground between L's
    smaller codes and H's better damage tolerance). `border=0` is passed to
    the library so `get_matrix()` returns ONLY the data/finder/timing
    matrix, no quiet zone baked in -- WE draw the (4-module) quiet zone
    explicitly by offsetting every rect in `_row_rects`, so it's accounted
    for in `width_px`/`height_px` like everywhere else in this module,
    rather than living inside a library-owned matrix we'd have to trust.
    Version is left to the library (`qr.make(fit=True)`, no explicit
    version=) -- it picks the smallest version that fits `data` at
    ERROR_CORRECT_M, which is what "auto" sizing (barcode_label.py) needs:
    the resulting matrix size (always square, always odd, >=21) IS the
    content-driven module count that auto sizing measures via a module_px=1
    probe call.
    """
    warnings: list[RenderWarning] = []
    qr = qrcode.QRCode(error_correction=_QR_ERROR_CORRECTION, border=0)
    qr.add_data(data)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    n = len(matrix)
    size_px = (n + 2 * _QR_QUIET_MODULES) * module_px

    if module_px < _SMALL_MODULE_PX:
        warnings.append(_small_module_warning(object_id, module_px, "QR code"))
    if size_px > _MAX_HEAD_DOTS:
        warnings.append(_large_barcode_warning(object_id, size_px, "QR code"))

    rects = _row_rects(matrix, module_px, _QR_QUIET_MODULES)
    svg_group = _group(x, y, rects)
    return BarcodeResult(
        svg_group=svg_group, width_px=size_px, height_px=size_px, warnings=warnings
    )


def qr_fit_group(data: str, height_px: int) -> tuple[str, int, list[RenderWarning]]:
    """QR sized to the largest module (<= `_FIT_MAX_MODULE_PX`) that fits
    `height_px`, quiet zone included. Returns the code's own (0,0)-relative
    SVG group, its square pixel size, and `qr_object`'s own warnings. Raises
    ValueError if even 1px modules don't fit. Shared by homebox_asset.py,
    cable_wrap.py and cable_flag.py."""
    total_modules = qr_object(data, module_px=1).width_px
    module_px = height_px // total_modules
    if module_px < 1:
        raise ValueError(
            f"QR code needs at least {total_modules}px of print height (only "
            f"{height_px}px available on this tape) -- try a taller tape"
        )
    module_px = min(module_px, _FIT_MAX_MODULE_PX)
    result = qr_object(data, module_px=module_px)
    return result.svg_group, result.width_px, result.warnings


def _bars_object(
    symbology_name: str,
    barcode_obj,
    *,
    x_dim_px: int,
    height_px: int,
    x: int,
    y: int,
    object_id: str | None,
) -> BarcodeResult:
    """Shared Code128/Code39 rendering: both are 1D "bars", differing only in
    which python-barcode class built `barcode_obj` and what label a warning
    should use -- everything about turning its `build()` module string into
    a pixel-snapped rect group is identical."""
    warnings: list[RenderWarning] = []
    module_string = barcode_obj.build()[0]
    runs = _module_runs(module_string)
    total_modules = sum(width for _, width in runs)
    width_px = (total_modules + 2 * _BARS_QUIET_MODULES) * x_dim_px

    if x_dim_px < _SMALL_MODULE_PX:
        warnings.append(_small_module_warning(object_id, x_dim_px, symbology_name))

    rects: list[str] = []
    cursor_modules = _BARS_QUIET_MODULES
    for is_bar, width_modules in runs:
        if is_bar:
            rects.append(
                _rect(cursor_modules * x_dim_px, 0, width_modules * x_dim_px, height_px)
            )
        cursor_modules += width_modules

    svg_group = _group(x, y, rects)
    return BarcodeResult(
        svg_group=svg_group, width_px=width_px, height_px=height_px, warnings=warnings
    )


def code128_object(
    data: str,
    *,
    x_dim_px: int,
    height_px: int,
    x: int = 0,
    y: int = 0,
    object_id: str | None = None,
) -> BarcodeResult:
    """Code128 via python-barcode's `Code128.build()` -- consumes the bar
    STRUCTURE (a list of 0/1-per-module strings; see `_module_runs`), never
    `Code128.render()`/its SVGWriter (which would draw its own quiet
    zone/module width in physical mm, not integer device pixels, plus
    human-readable text we render ourselves in barcode_label.py's caption).
    The library picks charset A/B/C automatically per Code128's own spec and
    appends its own check digit -- both are Code128 requirements, not
    optional behavior this module would ever want to skip.
    """
    barcode_cls = barcode.get_barcode_class("code128")
    return _bars_object(
        "Code128",
        barcode_cls(data),
        x_dim_px=x_dim_px,
        height_px=height_px,
        x=x,
        y=y,
        object_id=object_id,
    )


def code39_object(
    data: str,
    *,
    x_dim_px: int,
    height_px: int,
    x: int = 0,
    y: int = 0,
    object_id: str | None = None,
) -> BarcodeResult:
    """Code39 via python-barcode's `Code39.build()`, same bar-structure
    convention as `code128_object`. Charset (`CODE39_CHARSET`: digits,
    uppercase A-Z, -. $/+% and space -- ISO/IEC 16388) is validated HERE,
    before ever calling into the library, so an invalid character raises a
    `ValueError` naming every offending character -- not python-barcode's
    own `IllegalCharacterError` (a different exception type a caller would
    need to know to catch, with a message this module doesn't control).
    `add_checksum=False`: Code39's Mod-43 check character is optional per
    spec and not mentioned by this task's brief; adding one silently would
    mean the barcode encodes one MORE character than `data` itself, which
    would be a surprising mismatch between what a caller asked to encode and
    what actually got encoded.
    """
    invalid = sorted({ch for ch in data if ch not in CODE39_CHARSET})
    if invalid:
        raise ValueError(
            f"code39 data contains invalid character(s) {invalid}; valid charset is "
            "digits, uppercase A-Z, and -. $/+% and space"
        )
    barcode_cls = barcode.get_barcode_class("code39")
    return _bars_object(
        "Code39",
        barcode_cls(data, add_checksum=False),
        x_dim_px=x_dim_px,
        height_px=height_px,
        x=x,
        y=y,
        object_id=object_id,
    )


def datamatrix_object(
    data: str, *, module_px: int, x: int = 0, y: int = 0, object_id: str | None = None
) -> BarcodeResult:
    """DataMatrix via `ppf.datamatrix.DataMatrix.matrix` -- a plain
    list-of-rows of 0/1 ints for the full ECC200 symbol (finder pattern
    included), read directly rather than parsing the library's own `svg()`
    path string (see module docstring: `.matrix` is the same data one
    property away, so there's nothing to gain from round-tripping through
    SVG). `rect=False` (the library default, not overridden) -- always a
    square symbol, matching the "square matrix" the task brief's test
    requirements ask for. 2-module quiet zone (see module docstring for why
    2, not the spec's 1-module minimum).
    """
    warnings: list[RenderWarning] = []
    dm = DataMatrix(data)
    matrix = dm.matrix
    n = len(matrix)
    size_px = (n + 2 * _DM_QUIET_MODULES) * module_px

    if module_px < _SMALL_MODULE_PX:
        warnings.append(_small_module_warning(object_id, module_px, "DataMatrix code"))
    if size_px > _MAX_HEAD_DOTS:
        warnings.append(_large_barcode_warning(object_id, size_px, "DataMatrix code"))

    rects = _row_rects(matrix, module_px, _DM_QUIET_MODULES)
    svg_group = _group(x, y, rects)
    return BarcodeResult(
        svg_group=svg_group, width_px=size_px, height_px=size_px, warnings=warnings
    )
