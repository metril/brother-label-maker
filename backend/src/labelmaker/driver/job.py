"""Job builder: assembles complete, wire-ready byte streams from one or more
label images, a tape spec, an init strategy, and chain-mode options.

Chain-mode assembly rules (FF/CTRL_Z placement, cut-mark line construction)
follow docs/hardware-probe-notes.md's protocol quick-reference and Brother's family raster
manual for the PT-E550W/P750W/P710BT (see docs/hardware-probe-notes.md's References section
for the download link).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PIL import Image

from labelmaker.driver.geometry import TapeSpec
from labelmaker.driver.protocol import ChainMode
from labelmaker.driver.raster import (
    BYTES_PER_LINE,
    ZERO_LINE,
    RasterConfig,
    encode_image,
    encode_line,
    image_to_pin_lines,
    set_pin,
)

if TYPE_CHECKING:
    from labelmaker.driver.strategies import InitStrategy

_DEFAULT_RASTER_CONFIG = RasterConfig()

# ChainMode now lives in protocol.py (str-valued, Task 1.3a) -- re-exported
# here so existing `from labelmaker.driver.job import ChainMode` imports
# keep working.
__all__ = ["ChainMode", "JobOptions", "JobStream", "build_job"]


@dataclass(frozen=True)
class JobOptions:
    chain_mode: ChainMode = ChainMode.CUT_EACH
    auto_cut: bool = True
    margin_mm: float = 2.0
    raster_config: RasterConfig = _DEFAULT_RASTER_CONFIG
    cut_mark_width: int = 4
    cut_mark_gap: int = 4


@dataclass(frozen=True)
class JobStream:
    data: bytes
    page_count: int
    total_raster_lines: int
    strategy_name: str
    chain_mode: ChainMode


def _cut_mark_line(tape: TapeSpec, raster_config: RasterConfig) -> bytes:
    """One 16-byte pin line, dashed within the print area only: pins where
    ((pin - tape.left_pin) // 4) % 2 == 0 are set.

    Packed via raster.py's shared set_pin() helper, honoring
    `raster_config.bit_order` (task 2.1 review fix-up: this used to hardcode
    MSB-first packing inline instead of sharing raster.py's pin-packing
    logic, so it silently ignored a non-default RasterConfig.bit_order --
    see set_pin's docstring). Deliberately does NOT track `flip_pins`: cut
    marks are synthetic, not image-derived -- `flip_pins` only affects how
    an image's row axis maps onto pin numbers (image_to_pin_lines), which
    has no meaning for this offset-within-the-print-area dash pattern.
    With the default RasterConfig (MSB_FIRST), this produces byte-identical
    output to the pre-2.9 hardcoded implementation -- see test_job.py's
    golden test_strip_marks_two_images_full_stream, unchanged.
    """
    line = bytearray(BYTES_PER_LINE)
    for offset in range(tape.print_dots):
        if (offset // 4) % 2 == 0:
            pin = tape.left_pin + offset
            set_pin(line, pin, raster_config.bit_order)
    return bytes(line)


def _build_chained(
    images: list[Image.Image],
    tape: TapeSpec,
    strategy: InitStrategy,
    options: JobOptions,
) -> JobStream:
    pages = [
        encode_image(img, tape, strategy.compression, options.raster_config) for img in images
    ]
    # encode_image validates mode/height/width per image; a mixed-height list
    # raises ValueError here, from the raster layer -- not pre-checked or caught.

    n_pages = len(images)
    parts: list[bytes] = []
    total_lines = 0

    if options.chain_mode is ChainMode.CUT_EACH:
        for frames in pages:
            parts.append(strategy.preamble(tape, options))
            parts.append(strategy.page_header(tape, len(frames), True))
            parts.extend(frames)
            parts.append(strategy.page_end(True))
            total_lines += len(frames)
    else:  # CHAIN_FF
        parts.append(strategy.preamble(tape, options))
        for i, frames in enumerate(pages):
            is_last = i == n_pages - 1
            parts.append(strategy.page_header(tape, len(frames), i == 0))
            parts.extend(frames)
            parts.append(strategy.page_end(is_last))
            total_lines += len(frames)

    return JobStream(
        data=b"".join(parts),
        page_count=n_pages,
        total_raster_lines=total_lines,
        strategy_name=strategy.name,
        chain_mode=options.chain_mode,
    )


def _build_strip_marks(
    images: list[Image.Image],
    tape: TapeSpec,
    strategy: InitStrategy,
    options: JobOptions,
) -> JobStream:
    per_image_lines = [image_to_pin_lines(img, tape, options.raster_config) for img in images]
    # image_to_pin_lines validates mode/height/width per image; a mixed-height
    # list raises ValueError here, from the raster layer -- not pre-checked or caught.

    cut_mark = _cut_mark_line(tape, options.raster_config)
    gap = [ZERO_LINE] * options.cut_mark_gap
    dashes = [cut_mark] * options.cut_mark_width

    combined: list[bytes] = []
    for i, lines in enumerate(per_image_lines):
        if i > 0:
            combined += gap + dashes + gap
        combined += lines

    frames = [encode_line(pins, strategy.compression) for pins in combined]

    data = b"".join(
        [strategy.preamble(tape, options), strategy.page_header(tape, len(combined), True)]
        + frames
        + [strategy.page_end(True)]
    )

    return JobStream(
        data=data,
        page_count=1,
        total_raster_lines=len(combined),
        strategy_name=strategy.name,
        chain_mode=options.chain_mode,
    )


def build_job(
    images: list[Image.Image],
    tape: TapeSpec,
    strategy: InitStrategy,
    options: JobOptions,
) -> JobStream:
    if not images:
        raise ValueError("images must be non-empty")

    if options.chain_mode is ChainMode.STRIP_MARKS:
        return _build_strip_marks(images, tape, strategy, options)
    return _build_chained(images, tape, strategy, options)
