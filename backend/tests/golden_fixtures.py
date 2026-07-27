"""Golden-PNG fixture definitions: the single source of truth both
test_text_label.py's golden byte-lock tests and scripts/regen_goldens.py
render from, so the two can never drift out of sync with each other -- a
fixture added/changed here is immediately what both the test assertions and
the regen script use, with no second copy to remember to update.
"""

from dataclasses import dataclass

from labelmaker.render.types.text_label import TextLabelParams

# Upscale factor golden PNGs are encoded at (preview_png's `scale`) -- purely
# a golden-fixture convention (makes the committed PNGs bigger/easier to eyeball
# than the raw device-dot bitmap), unrelated to any real API default.
GOLDEN_SCALE = 4


@dataclass(frozen=True)
class GoldenFixture:
    name: str  # golden file is tests/golden/render/{name}.png
    params: TextLabelParams
    tape_mm: float
    tape_family: str = "tze"


FIXTURES: tuple[GoldenFixture, ...] = (
    GoldenFixture(
        name="text_hello_inter_24mm",
        params=TextLabelParams(lines=["HELLO"]),
        tape_mm=24,
    ),
    GoldenFixture(
        name="text_two_line_robotocondensed_bold_12mm",
        params=TextLabelParams(
            lines=["PATCH PANEL", "PORT 1-24"], font_family="Roboto Condensed", bold=True
        ),
        tape_mm=12,
    ),
    GoldenFixture(
        name="text_port01_jetbrainsmono_fixed40mm_left_24mm",
        params=TextLabelParams(
            lines=["PORT-01"], font_family="JetBrains Mono", length_mm=40.0, h_align="left"
        ),
        tape_mm=24,
    ),
)
