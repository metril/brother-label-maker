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

from labelmaker.driver.geometry import MARGIN_MIN_MM, TapeSpec
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
__all__ = [
    "ChainMode",
    "JobOptions",
    "JobStream",
    "build_feed_cut_job",
    "build_job",
    "feed_cut_image",
    "feed_cut_options",
]


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


# --- Feed & cut trigger job ---------------------------------------------
#
# docs/superpowers/specs/2026-08-04-feed-cut-trigger-design.md: a manual
# "advance tape past the cutter and cut" action for when a chained job (or
# auto-cut off) leaves printed tape sitting inside the mechanism.


def feed_cut_image(tape: TapeSpec) -> Image.Image:
    """The blank "page" a feed-cut job prints: 1 dot wide, `tape.print_dots`
    tall, ALL WHITE (PIL mode "1", pixel value 1 -- see raster.py's bit
    semantics: pixel 0 is black, so an all-1 image has no black pixel
    anywhere). Every raster line build_job/raster.py encodes for it is
    therefore the raster layer's own all-zero ZERO_LINE -- nothing ever
    prints, only the mechanical feed+cut happens.

    Public (not `_`-prefixed) and separate from build_feed_cut_job below so
    a caller that must resolve the tape from a LIVE printer status first
    (jobs/worker.py's feed-cut branch, driver/cli.py's feed-cut USB path --
    both mirror cli.py's existing _run_usb_print, which has this exact same
    status-before-image-size constraint for its own test patterns) can
    build this same image and hand it to printer.print_images directly,
    instead of only being reachable through build_feed_cut_job's own
    build_job call.
    """
    return Image.new("1", (1, tape.print_dots), 1)


def feed_cut_options() -> JobOptions:
    """The fixed JobOptions every feed-cut job uses -- see
    build_feed_cut_job's docstring for why each value is what it is.
    Exposed separately (mirrors feed_cut_image above) so callers that go
    through printer.print_images directly, not build_feed_cut_job, still
    use the exact same options build_feed_cut_job would have."""
    return JobOptions(
        auto_cut=True,
        chain_mode=ChainMode.CUT_EACH,
        margin_mm=MARGIN_MIN_MM,
    )


def build_feed_cut_job(tape: TapeSpec, strategy: InitStrategy) -> JobStream:
    """Feed-and-cut trigger job: reuses build_job() unchanged (no new
    protocol bytes -- the whole point of this function is that none are
    needed) with a single blank page, producing preamble -> one-line
    `ESC i z` -> one zero raster line -> `CTRL_Z`.

    THE CONSTRAINT THAT DRIVES THIS (docs/superpowers/specs/
    2026-08-04-feed-cut-trigger-design.md): the P-touch raster protocol has
    no standalone "cut" opcode. A cut only ever happens at end-of-page
    (`FF`/`CTRL_Z` -- strategies.InitStrategy.page_end) with the auto-cut
    bit set (`ESC i M` 0x40) -- there is no way to trigger the blade
    without also feeding a page through the print head first. Mechanically
    the cutter sits ~24.5mm downstream of the head (`geometry.MIN_FEED_MM`,
    geometry.py:17), so every cut inherently advances tape by at least that
    much -- this job's image is deliberately the smallest build_job can
    build (feed_cut_image: 1 dot wide, all white) so nothing ELSE gets
    added to that inherent minimum.

    Options, and why each is fixed (not caller-configurable -- this
    function intentionally takes no `options` argument):
      - `chain_mode=ChainMode.CUT_EACH`: cut once and stop -- CUT_EACH's
        page_end for a single-image job is always CTRL_Z, never a chained
        FF (see _build_chained).
      - `auto_cut=True`: without the auto-cut bit, end-of-page feeds but
        does NOT cut -- the one bit this whole job exists to set.
      - `margin_mm=MARGIN_MIN_MM`: "minimized margins" (the design doc's
        phrasing) resolves to exactly `geometry.MARGIN_MIN_MM` (2.0mm) --
        `clamp_margin_mm` floors ANY smaller value up to this same 2.0mm
        anyway (geometry.py), so this is the smallest margin the existing
        JobOptions/strategies machinery allows, not an arbitrary pick.
        `ClassicStrategy.preamble` encodes it as `mm_to_dots(2.0) == 14`
        dots -- little-endian `\\x0e\\x00` in `ESC i d` -- the exact same
        literal test_job.py's own golden tests already use for a 2.0mm
        margin (JobOptions.margin_mm's own default, not a new value this
        function introduces).
      - `raster_config`: left at JobOptions' plain default. feed_cut_image
        has no black pixel anywhere, so bit_order/flip_pins can never
        change a single byte of the output -- there is nothing for a
        non-default RasterConfig to affect here.

    UNVERIFIED (repo convention -- see docs/protocol-notes.md): the EXACT
    physical tape distance a real PT-E720BT advances for this job is not
    yet measured against hardware. It is almost certainly `MIN_FEED_MM`
    (~24.5mm, the mechanical head-to-cutter gap every cut inherently
    requires -- see the design doc's own framing: that advance is either
    the user's printed tape clearing the blade after a chained job, or a
    blank ~24.5mm snippet when triggered with nothing pending), but this is
    a software-level inference, not a physical measurement. Confirm at
    physical checkpoint 2 (docs/project-handoff.md's checkpoint-2 list)
    alongside every other UNVERIFIED byte-level decision this driver
    package carries.

    UNVERIFIED, and a bigger risk than the feed-distance question above --
    e310bt strategy has no ESC i M at all: `E310BTStrategy.preamble`
    (strategies.py) never emits the auto-cut byte the classic strategy's
    preamble does (`\\x1b\\x69\\x4d` / 0x40); under `printer_init_strategy
    ="e310bt"` this job's ability to actually CUT rests entirely on `ESC i
    K`'s no-chain bit (set here via CUT_EACH -> `_no_chain`), with no
    corroborating auto-cut bit anywhere in the stream. If the real e310bt
    firmware needs BOTH bits (no-chain AND auto-cut) to fire the blade --
    plausible, since the classic strategy always sets both together and
    nothing has verified them independently -- a feed-cut job under this
    strategy would silently FEED without CUTTING: no error, no exception,
    tape advances ~24.5mm and the job reports "done", but the user's tape
    is still uncut and the whole point of the trigger silently fails. This
    is deliberately NOT fixed by adding bytes here: e310bt's preamble is
    intentionally minimal and golden-tested (test_job.py/test_job_feed_cut.
    py), and inventing an untested byte sequence for unverified hardware
    risks making things WORSE than a known gap. Tracked instead as a
    checkpoint-2 hardware question (docs/project-handoff.md's "Still
    waiting on hardware" list) -- if hardware confirms the no-chain bit
    alone doesn't cut under e310bt, feed-cut must either emit `ESC i M`
    under that strategy too or be gated/warned against when
    printer_init_strategy="e310bt", not before.
    """
    return build_job([feed_cut_image(tape)], tape, strategy, feed_cut_options())
