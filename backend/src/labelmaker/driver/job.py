"""Job builder: assembles complete, wire-ready byte streams from one or more
label images, a tape spec, an init strategy, and chain-mode options. See
task-0.5-brief.md for the chain-mode assembly rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

from PIL import Image

from labelmaker.driver.geometry import TapeSpec
from labelmaker.driver.raster import (
    BYTES_PER_LINE,
    ZERO_LINE,
    RasterConfig,
    encode_image,
    encode_line,
    image_to_pin_lines,
)

if TYPE_CHECKING:
    from labelmaker.driver.strategies import InitStrategy

_DEFAULT_RASTER_CONFIG = RasterConfig()


class ChainMode(Enum):
    CUT_EACH = auto()
    CHAIN_FF = auto()
    STRIP_MARKS = auto()


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


def _cut_mark_line(tape: TapeSpec) -> bytes:
    """One 16-byte pin line, dashed within the print area only: pins where
    ((pin - tape.left_pin) // 4) % 2 == 0 are set. Packed MSB-first (byte =
    pin // 8, bit = 7 - pin % 8) -- cut marks are synthetic, not image-derived,
    so unlike raster.py's image pipeline they don't track RasterConfig's
    bit_order/flip_pins flags.
    """
    line = bytearray(BYTES_PER_LINE)
    for offset in range(tape.print_dots):
        if (offset // 4) % 2 == 0:
            pin = tape.left_pin + offset
            byte_index = pin // 8
            bit = 7 - pin % 8
            line[byte_index] |= 1 << bit
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

    cut_mark = _cut_mark_line(tape)
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
