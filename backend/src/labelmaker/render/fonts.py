"""Bundled hermetic fonts + Pillow-based layout measurement helpers.

Fonts are bundled (not system fonts) so preview and print never depend on
what happens to be installed on the host -- see rasterize.py, which points
resvg at FONTS_DIR with system fonts disabled. measure_text/fit_font_size
use the SAME TTF files via Pillow purely to guide layout (auto font size,
auto label length); resvg does the actual rendering, so small metric drift
between Pillow's and resvg's text-shaping engines is acceptable -- it is
absorbed by a safety margin (see fit_font_size).
"""

from pathlib import Path

from PIL import ImageFont
from pydantic import BaseModel

# Assets live outside the installed package, at backend/assets/fonts,
# sibling to backend/src/. Path(__file__).resolve().parents[3] walks
# render/ -> labelmaker/ -> src/ -> backend/. This resolves correctly for
# an editable install (uv run from backend/) and for a Docker image that
# COPies the whole backend/ tree preserving this layout; it would NOT
# resolve if labelmaker were installed as a standalone wheel elsewhere
# without backend/assets/ alongside it -- out of scope for this task.
FONTS_DIR = Path(__file__).resolve().parents[3] / "assets" / "fonts"

# Default (non-fitting) SVG font-size guess and the fraction of a fixed
# width budget fit_font_size is allowed to use -- see its docstring.
_WIDTH_SAFETY_MARGIN = 0.95
_DEFAULT_LINE_SPACING = 1.15


class FontInfo(BaseModel):
    family: str
    display_name: str
    monospace: bool
    has_bold: bool


# The four bundled families, hardcoded rather than discovered from the TTFs'
# name tables (per the brief: keep it simple) -- the family names below are
# asserted to match what the files actually declare in test_fonts.py.
_BUNDLED_FONTS: tuple[FontInfo, ...] = (
    FontInfo(family="Inter", display_name="Inter", monospace=False, has_bold=True),
    FontInfo(
        family="Roboto Condensed", display_name="Roboto Condensed", monospace=False, has_bold=True
    ),
    FontInfo(family="JetBrains Mono", display_name="JetBrains Mono", monospace=True, has_bold=True),
    FontInfo(family="DejaVu Sans", display_name="DejaVu Sans", monospace=False, has_bold=True),
)

_FILES: dict[tuple[str, bool], str] = {
    ("Inter", False): "Inter-Regular.ttf",
    ("Inter", True): "Inter-Bold.ttf",
    ("Roboto Condensed", False): "RobotoCondensed-Regular.ttf",
    ("Roboto Condensed", True): "RobotoCondensed-Bold.ttf",
    ("JetBrains Mono", False): "JetBrainsMono-Regular.ttf",
    ("JetBrains Mono", True): "JetBrainsMono-Bold.ttf",
    ("DejaVu Sans", False): "DejaVuSans.ttf",
    ("DejaVu Sans", True): "DejaVuSans-Bold.ttf",
}


def list_fonts() -> list[FontInfo]:
    return list(_BUNDLED_FONTS)


def ensure_fonts_dir() -> None:
    """Raise loudly if FONTS_DIR doesn't exist.

    Without this, a missing/misplaced fonts directory degrades silently:
    resvg raises nothing and draws nothing for a font_dirs entry that
    doesn't exist (or for a font-family with no matching loaded font) --
    the caller gets a blank all-white bitmap back, not an error. That's the
    failure mode this guards against, so it's checked at first use (here,
    and by rasterize.py before ever invoking resvg) rather than only once
    at import time -- callers/tests can point FONTS_DIR elsewhere and the
    check still fires on the next call, instead of only ever running against
    whatever FONTS_DIR resolved to when this module first loaded.
    """
    if not FONTS_DIR.is_dir():
        raise RuntimeError(
            f"fonts directory not found: {FONTS_DIR} -- expected backend/assets/fonts "
            "alongside backend/src/ (see labelmaker.render.fonts.FONTS_DIR's docstring "
            "for the layout assumption this depends on)"
        )


def font_path(family: str, bold: bool = False) -> Path:
    ensure_fonts_dir()
    key = (family, bold)
    if key not in _FILES:
        valid = sorted({f for f, _ in _FILES})
        raise ValueError(f"unknown font family {family!r}; valid families: {valid}")
    return FONTS_DIR / _FILES[key]


def measure_text(text: str, family: str, size_px: float, bold: bool = False) -> tuple[int, int]:
    """Measure text as Pillow/FreeType would lay it out at size_px. Guides
    layout only -- see module docstring."""
    font = ImageFont.truetype(str(font_path(family, bold)), size_px)
    left, top, right, bottom = font.getbbox(text)
    return (right - left, bottom - top)


def fit_font_size(
    lines: list[str],
    family: str,
    max_width_px: float | None,
    max_height_px: float,
    bold: bool = False,
    line_spacing: float = _DEFAULT_LINE_SPACING,
    min_px: int = 6,
    max_px: int = 128,
) -> int:
    """Largest integer px size where all lines fit.

    Height fit: len(lines) * size * line_spacing <= max_height_px (an
    approximate line-box model -- font size stands in for line height,
    scaled by line_spacing; exact ascent/descent metrics are a rendering
    concern, not a fitting concern).

    Width fit (only when max_width_px is given): every line's measured
    width must be <= max_width_px * _WIDTH_SAFETY_MARGIN (0.95). The 5%
    margin exists because resvg's text shaping can differ slightly from
    Pillow's measurement -- reserving it means a size that "fits" here still
    fits after the real render, never the reverse.

    Falls back to min_px if nothing in [min_px, max_px] fits (the caller is
    expected to warn that the result may be cramped).
    """
    non_empty_lines = [line for line in lines if line]
    for size in range(max_px, min_px - 1, -1):
        if len(lines) * size * line_spacing > max_height_px:
            continue
        if max_width_px is not None and non_empty_lines:
            widest = max(measure_text(line, family, size, bold)[0] for line in non_empty_lines)
            if widest > max_width_px * _WIDTH_SAFETY_MARGIN:
                continue
        return size
    return min_px
