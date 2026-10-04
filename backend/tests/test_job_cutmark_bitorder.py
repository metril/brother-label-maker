"""Tests for task 2.9's cut-mark bit-order fix: driver/job.py's
_cut_mark_line now packs pins via raster.py's shared set_pin() helper
(honoring RasterConfig.bit_order) instead of a hardcoded MSB-first
computation -- the task 2.1 review's original ask.

NOT part of test_job.py/test_job_supplement.py's golden set (this is a new
file, added for this task) -- but this fix must NOT change ANY byte of
those golden streams, since they all use the DEFAULT RasterConfig
(bit_order=MSB_FIRST); see test_job.py/test_raster.py's own runs, unchanged,
for that guarantee. This file instead pins the NEW behavior: a non-default
(LSB_FIRST) RasterConfig now actually changes the cut-mark bytes (previously
silently ignored), while still marking the exact same PHYSICAL pins.

Expected byte literals are hand-computed exactly per test_job.py's own
conventions (never obtained by calling the code under test) -- see the
derivation comments below.
"""

from PIL import Image

from labelmaker.driver.geometry import MediaFamily, find_tape
from labelmaker.driver.job import ChainMode, JobOptions, build_job
from labelmaker.driver.raster import BYTES_PER_LINE, BitOrder, RasterConfig, set_pin
from labelmaker.driver.strategies import ClassicStrategy

TAPE_24MM = find_tape(24, MediaFamily.TZE)  # left_pin=0, print_dots=128
assert TAPE_24MM is not None and TAPE_24MM.left_pin == 0 and TAPE_24MM.print_dots == 128


# --- 1. set_pin() itself: MSB vs LSB packing of the same pin, hand-computed ---


def test_set_pin_msb_first_pin0_sets_byte0_bit7():
    line = bytearray(BYTES_PER_LINE)
    set_pin(line, 0, BitOrder.MSB_FIRST)
    assert bytes(line) == bytes([0x80]) + bytes(15)


def test_set_pin_lsb_first_pin0_sets_byte0_bit0():
    line = bytearray(BYTES_PER_LINE)
    set_pin(line, 0, BitOrder.LSB_FIRST)
    assert bytes(line) == bytes([0x01]) + bytes(15)


def test_set_pin_default_bit_order_is_msb_first():
    # set_pin's own default parameter (no RasterConfig involved) -- must
    # match MSB_FIRST so a caller that forgets to pass bit_order explicitly
    # still gets the pre-2.9 hardcoded behavior, not a silent LSB flip.
    line = bytearray(BYTES_PER_LINE)
    set_pin(line, 9)  # byte 1, MSB bit 7-(9%8)=7-1=6 -> mask 0x40
    assert bytes(line) == bytes(1) + bytes([0x40]) + bytes(14)


# --- 2. Cut-mark line pin pattern, hand-derived for TAPE_24MM (left_pin=0) ---
#
# _cut_mark_line sets pin=offset for offset in range(128) where
# (offset // 4) % 2 == 0 -- i.e. within every group of 8 pins, the LOW 4
# (pin % 8 in [0,3]) are set and the HIGH 4 (pin % 8 in [4,7]) are not; this
# pattern is identical across all 16 byte-groups (128 pins). See
# test_job.py's test_strip_marks_two_images_full_stream derivation comment
# for the MSB_FIRST case (0xF0 per byte) this cross-checks.
#
# MSB_FIRST: bit = 7 - pin%8 -> pin%8 in [0,3] -> bits 7,6,5,4 set -> 0xF0.
# LSB_FIRST: bit = pin%8     -> pin%8 in [0,3] -> bits 0,1,2,3 set -> 0x0F.

_EXPECTED_CUT_MARK_PINS = {pin for pin in range(TAPE_24MM.print_dots) if (pin // 4) % 2 == 0}


def _decode_pins(line: bytes, bit_order: BitOrder) -> set[int]:
    pins = set()
    for byte_index, byte in enumerate(line):
        for bit_pos in range(8):
            if byte & (1 << bit_pos):
                pin = byte_index * 8 + (bit_pos if bit_order is BitOrder.LSB_FIRST else 7 - bit_pos)
                pins.add(pin)
    return pins


def test_cut_mark_line_msb_bytes_are_0xf0():
    from labelmaker.driver.job import _cut_mark_line

    line = _cut_mark_line(TAPE_24MM, RasterConfig(bit_order=BitOrder.MSB_FIRST))
    assert line == b"\xf0" * BYTES_PER_LINE
    assert _decode_pins(line, BitOrder.MSB_FIRST) == _EXPECTED_CUT_MARK_PINS


def test_cut_mark_line_lsb_bytes_are_0x0f():
    from labelmaker.driver.job import _cut_mark_line

    line = _cut_mark_line(TAPE_24MM, RasterConfig(bit_order=BitOrder.LSB_FIRST))
    assert line == b"\x0f" * BYTES_PER_LINE
    assert _decode_pins(line, BitOrder.LSB_FIRST) == _EXPECTED_CUT_MARK_PINS


def test_cut_mark_line_msb_and_lsb_differ_but_decode_to_same_pin_set():
    from labelmaker.driver.job import _cut_mark_line

    msb_line = _cut_mark_line(TAPE_24MM, RasterConfig(bit_order=BitOrder.MSB_FIRST))
    lsb_line = _cut_mark_line(TAPE_24MM, RasterConfig(bit_order=BitOrder.LSB_FIRST))

    assert msb_line != lsb_line  # the bug this fixes: LSB used to be silently ignored
    assert _decode_pins(msb_line, BitOrder.MSB_FIRST) == _decode_pins(lsb_line, BitOrder.LSB_FIRST)
    assert _decode_pins(msb_line, BitOrder.MSB_FIRST) == _EXPECTED_CUT_MARK_PINS


# --- 3. End-to-end via build_job: STRIP_MARKS stream under LSB differs from ---
# MSB only in the cut-mark frame bytes; blank (all-white) images keep every
# OTHER frame identical (an all-white pin line has no bits set at all, so
# its PACKBITS encoding -- the 'Z' all-zero shorthand -- is bit_order-
# independent), isolating the cut-mark fix as the sole source of difference.


def _blank_image(width: int = 1) -> Image.Image:
    return Image.new("1", (width, TAPE_24MM.print_dots), 1)  # all white


# PACKBITS frame for a uniform 16-byte line (one repeat-run): header =
# 257-16 = 241 = 0xF1, followed by the repeated byte -- same derivation
# test_job.py uses for CUT_MARK_FRAME_PB (0xF0 case); 0x0F is the LSB
# mirror image of that same bit pattern.
_CUT_MARK_FRAME_MSB = b"\x47\x02\x00\xf1\xf0"
_CUT_MARK_FRAME_LSB = b"\x47\x02\x00\xf1\x0f"


def test_strip_marks_stream_lsb_vs_msb_differ_only_in_cut_mark_frames():
    strategy = ClassicStrategy()
    images = [_blank_image(), _blank_image()]

    msb_opts = JobOptions(
        chain_mode=ChainMode.STRIP_MARKS, raster_config=RasterConfig(bit_order=BitOrder.MSB_FIRST)
    )
    lsb_opts = JobOptions(
        chain_mode=ChainMode.STRIP_MARKS, raster_config=RasterConfig(bit_order=BitOrder.LSB_FIRST)
    )
    msb_result = build_job(images, TAPE_24MM, strategy, msb_opts)
    lsb_result = build_job(images, TAPE_24MM, strategy, lsb_opts)

    assert msb_result.data != lsb_result.data
    # Exactly 4 cut-mark frames appear (cut_mark_width default = 4), each
    # frame's bytes replaced by its LSB mirror -- and nothing else changes:
    # swapping every MSB cut-mark frame for its LSB counterpart in the MSB
    # stream reproduces the LSB stream exactly (both preamble/page-header/
    # blank-image/CTRL_Z bytes are bit_order-independent here).
    assert msb_result.data.count(_CUT_MARK_FRAME_MSB) == 4
    assert lsb_result.data.count(_CUT_MARK_FRAME_LSB) == 4
    assert msb_result.data.replace(_CUT_MARK_FRAME_MSB, _CUT_MARK_FRAME_LSB) == lsb_result.data
    assert len(msb_result.data) == len(lsb_result.data)
