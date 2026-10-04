"""Tests for labelmaker.driver.job: chain-mode assembly into complete,
wire-ready byte streams.

Expected full-stream literals are assembled entirely by hand: protocol-byte
constants (from docs/hardware-probe-notes.md's protocol quick-reference and Brother's family
raster manual for the PT-E550W/P750W/P710BT -- see docs/hardware-probe-notes.md's References
section for the download link) plus frame-byte literals whose PackBits/RAW
derivation is commented at the point of definition below. No frame byte in
this file is obtained by calling `raster.encode_line`/`packbits.encode` (or
`strategies.py`/`job.py`, the code under test) -- every expected byte is a
literal, so a wrong 'G' marker, wrong LE-u16 length, wrong 'Z' shorthand, or a
PackBits payload error in `job.build_job`'s wiring would be caught here.
`raster.py` and `geometry.py` are already-merged, independently-tested
dependencies (task 0.2/0.3), used only for `BYTES_PER_LINE`/`ZERO_LINE`
constants and `find_tape`, never to compute an expectation.
"""

import pytest
from PIL import Image

from labelmaker.driver.geometry import MediaFamily, find_tape
from labelmaker.driver.job import ChainMode, JobOptions, build_job
from labelmaker.driver.raster import BYTES_PER_LINE, ZERO_LINE
from labelmaker.driver.strategies import CTRL_Z, FF, MAGIC, ClassicStrategy, E310BTStrategy

TAPE_24MM = find_tape(24, MediaFamily.TZE)  # left_pin=0, print_dots=128
TAPE_12MM = find_tape(12, MediaFamily.TZE)  # left_pin=29, print_dots=70
assert TAPE_24MM is not None and TAPE_24MM.left_pin == 0 and TAPE_24MM.print_dots == 128
assert TAPE_12MM is not None


def _blank_line(index: int, mask: int) -> bytes:
    line = bytearray(BYTES_PER_LINE)
    line[index] = mask
    return bytes(line)


# --- Hand-derived pin lines, reusing task 0.3's verified 24mm derivations ---
# col black at row0   -> pin left_pin+print_dots-1-0   = 127 -> byte15, mask 0x01
# col black at row127 -> pin left_pin+print_dots-1-127 = 0   -> byte0,  mask 0x80
LINE_ROW0 = _blank_line(15, 0x01)
LINE_ROW127 = _blank_line(0, 0x80)

# --- Frame bytes: hand-written literals -- NOT computed by calling encode_line ---
#
# RAW frame format (raster.py docstring): 0x47 + LE u16 length(=16) + the 16
# raw pin bytes verbatim.
FRAME_ROW0_RAW = b"\x47\x10\x00" + b"\x00" * 15 + b"\x01"
FRAME_ROW127_RAW = b"\x47\x10\x00" + b"\x80" + b"\x00" * 15

# PACKBITS frame format: 0x47 + LE u16 payload-length + PackBits payload.
# PackBits header semantics (Apple/TIFF PackBits, as implemented by the
# `packbits` pip dependency raster.py wraps): a header byte 0<=n<=127 means
# "copy the following n+1 bytes literally"; a header byte read as a signed
# value in -1..-127 means "repeat the following single byte (1-n) times"
# (as an unsigned byte: header = 257 - count, for 2 <= count <= 128).
#
# LINE_ROW0 = 15 zero bytes then one 0x01 byte:
#   repeat-run of 15 zeros: header = 257-15 = 242 = 0xF2, repeated byte 0x00
#   literal-run of 1 byte:  header = 1-1 = 0, literal byte 0x01
#   payload = F2 00 00 01 (4 bytes) -> frame = 47 04 00 F2 00 00 01
FRAME_ROW0_PB = b"\x47\x04\x00\xf2\x00\x00\x01"

# LINE_ROW127 = one 0x80 byte then 15 zero bytes:
#   literal-run of 1 byte:  header = 0, literal byte 0x80
#   repeat-run of 15 zeros: header = 0xF2, repeated byte 0x00
#   payload = 00 80 F2 00 (4 bytes) -> frame = 47 04 00 00 80 F2 00
FRAME_ROW127_PB = b"\x47\x04\x00\x00\x80\xf2\x00"

# Cut-mark line (all 16 bytes = 0xF0, derivation in test 5 below):
# repeat-run of 16 identical bytes: header = 257-16 = 241 = 0xF1, repeated
# byte 0xF0 -> payload = F1 F0 (2 bytes) -> frame = 47 02 00 F1 F0
CUT_MARK_FRAME_PB = b"\x47\x02\x00\xf1\xf0"

# All-zero line PACKBITS frame: raster.py's documented 'Z' (0x5A) shorthand
# for an all-zero 16-byte line -- a direct protocol fact (task 0.3), not a
# PackBits computation.
ZERO_FRAME_PB = b"Z"


def _two_col_image() -> Image.Image:
    """24mm-tall (128px) image, 2 columns: col0 black at row0, col1 black at row127."""
    img = Image.new("1", (2, 128), 1)  # all white
    img.putpixel((0, 0), 0)
    img.putpixel((1, 127), 0)
    return img


def _one_col_image(black_row: int) -> Image.Image:
    img = Image.new("1", (1, 128), 1)
    img.putpixel((0, black_row), 0)
    return img


# ESC i z params for the 2-col/24mm case: n1=0x84, n2=0x00, n3=0x18(24), n4=0x00,
# n5-n8=2 (LE u32 = 02 00 00 00), n9=0x00, n10=0x00
ESC_I_Z_2LINES_24MM = b"\x1b\x69\x7a\x84\x00\x18\x00\x02\x00\x00\x00\x00\x00"
# same, but n5-n8=1 (LE u32 = 01 00 00 00) -- single-column pages
ESC_I_Z_1LINE_24MM = b"\x1b\x69\x7a\x84\x00\x18\x00\x01\x00\x00\x00\x00\x00"


# --- 1. Classic single page, CHAIN_FF, 24mm, 2-col image, margin 2mm, auto-cut on ---


def test_classic_chain_ff_single_page_full_stream():
    strategy = ClassicStrategy()
    opts = JobOptions(chain_mode=ChainMode.CHAIN_FF, auto_cut=True, margin_mm=2.0)
    result = build_job([_two_col_image()], TAPE_24MM, strategy, opts)

    expected = (
        b"\x00" * 100
        + b"\x1b\x40"
        + b"\x1b\x69\x61\x01"
        + b"\x1b\x69\x4d\x40"
        + b"\x1b\x69\x4b\x00"
        + b"\x1b\x69\x64\x0e\x00"
        + b"\x4d\x02"
        + ESC_I_Z_2LINES_24MM
        + FRAME_ROW0_PB
        + FRAME_ROW127_PB
        + CTRL_Z
    )
    assert result.data == expected
    assert result.page_count == 1
    assert result.total_raster_lines == 2
    assert result.strategy_name == "classic"
    assert result.chain_mode is ChainMode.CHAIN_FF


# --- 2. E310BT single page, same image ---


def test_e310bt_single_page_full_stream():
    strategy = E310BTStrategy()
    opts = JobOptions(chain_mode=ChainMode.CHAIN_FF, auto_cut=True, margin_mm=2.0)
    result = build_job([_two_col_image()], TAPE_24MM, strategy, opts)

    expected = (
        b"\x00" * 100
        + b"\x1b\x40"
        + b"\x1b\x69\x61\x01"
        + b"\x1b\x69\x4b\x00"
        + ESC_I_Z_2LINES_24MM
        + MAGIC
        + FRAME_ROW0_RAW
        + FRAME_ROW127_RAW
        + CTRL_Z
    )
    assert result.data == expected
    assert MAGIC[5] == 0x4D
    assert b"\x4d\x02" not in result.data  # M 02 (PackBits select) must not appear
    assert result.strategy_name == "e310bt"


# --- 3. CHAIN_FF 2 pages (classic): exactly one FF, one trailing CTRL_Z ---


def test_classic_chain_ff_two_pages_full_stream():
    strategy = ClassicStrategy()
    opts = JobOptions(chain_mode=ChainMode.CHAIN_FF, auto_cut=True, margin_mm=2.0)
    img_a = _one_col_image(black_row=0)  # -> LINE_ROW0 pin bytes
    img_b = _one_col_image(black_row=127)  # -> LINE_ROW127 pin bytes
    result = build_job([img_a, img_b], TAPE_24MM, strategy, opts)

    preamble = (
        b"\x00" * 100
        + b"\x1b\x40"
        + b"\x1b\x69\x61\x01"
        + b"\x1b\x69\x4d\x40"
        + b"\x1b\x69\x4b\x00"
        + b"\x1b\x69\x64\x0e\x00"
        + b"\x4d\x02"
    )
    # each page is 1 raster line -> n5-n8 = 1 as LE u32
    expected = (
        preamble
        + ESC_I_Z_1LINE_24MM
        + FRAME_ROW0_PB
        + FF
        + ESC_I_Z_1LINE_24MM
        + FRAME_ROW127_PB
        + CTRL_Z
    )
    assert result.data == expected
    assert result.page_count == 2
    assert result.total_raster_lines == 2


# --- 3b. CHAIN_FF 2 pages (e310bt): magic follows only page 1's z, never page 2's
# (closes a coverage gap the single-page e310bt test can't: with N=1, is_first
# and is_last are both True, so a swapped is_first/is_last bug would slip past
# it. This directly exercises the "magic placement on chained pages" UNVERIFIED
# decision end-to-end through build_job, not just at the strategy unit level.)


def test_e310bt_chain_ff_two_pages_magic_only_on_first_page():
    strategy = E310BTStrategy()
    opts = JobOptions(chain_mode=ChainMode.CHAIN_FF, margin_mm=2.0)
    img_a = _one_col_image(black_row=0)
    img_b = _one_col_image(black_row=127)
    result = build_job([img_a, img_b], TAPE_24MM, strategy, opts)

    preamble = b"\x00" * 100 + b"\x1b\x40" + b"\x1b\x69\x61\x01" + b"\x1b\x69\x4b\x00"
    expected = (
        preamble
        + ESC_I_Z_1LINE_24MM
        + MAGIC
        + FRAME_ROW0_RAW
        + FF
        + ESC_I_Z_1LINE_24MM
        + FRAME_ROW127_RAW
        + CTRL_Z
    )
    assert result.data == expected
    assert result.data.count(MAGIC) == 1
    assert result.page_count == 2


# --- 4. CUT_EACH 2 images (classic): flush sequence appears exactly twice ---


def test_classic_cut_each_two_images_full_stream():
    strategy = ClassicStrategy()
    opts = JobOptions(chain_mode=ChainMode.CUT_EACH, auto_cut=True, margin_mm=2.0)
    img_a = _one_col_image(black_row=0)
    img_b = _one_col_image(black_row=127)
    result = build_job([img_a, img_b], TAPE_24MM, strategy, opts)

    preamble = (
        b"\x00" * 100
        + b"\x1b\x40"
        + b"\x1b\x69\x61\x01"
        + b"\x1b\x69\x4d\x40"
        + b"\x1b\x69\x4b\x08"  # CUT_EACH -> no-chain bit SET
        + b"\x1b\x69\x64\x0e\x00"
        + b"\x4d\x02"
    )
    z_1line = b"\x1b\x69\x7a\x84\x00\x18\x00\x01\x00\x00\x00\x00\x00"
    expected = (
        preamble
        + z_1line
        + FRAME_ROW0_PB
        + CTRL_Z
        + preamble
        + z_1line
        + FRAME_ROW127_PB
        + CTRL_Z
    )
    assert result.data == expected
    assert result.data.count(b"\x00" * 100) == 2  # flush sequence appears exactly twice
    assert result.page_count == 2
    assert result.total_raster_lines == 2


# --- 5. STRIP_MARKS 2x(2-col) images, 24mm, defaults ---
#
# combined line count = 2 (img1) + 4 (gap) + 4 (cutmark) + 4 (gap) + 2 (img2) = 16
# cut-mark line (24mm, left_pin=0): pins where (pin//4)%2==0 set. Pins 0-3 of
# every 8-pin byte group satisfy this ((0//4)%2=0, (1//4)%2=0, (2//4)%2=0,
# (3//4)%2=0), pins 4-7 don't ((4//4)%2=1 ... (7//4)%2=1) -> MSB-first packing
# puts pins 0-3 in bits 7-4 (set) and pins 4-7 in bits 3-0 (clear) -> 0xF0 per
# byte, for all 16 bytes (128 pins = whole 24mm print area).


def test_strip_marks_two_images_full_stream():
    strategy = ClassicStrategy()
    opts = JobOptions(chain_mode=ChainMode.STRIP_MARKS)
    result = build_job([_two_col_image(), _two_col_image()], TAPE_24MM, strategy, opts)

    cut_mark_line = b"\xf0" * BYTES_PER_LINE
    gap = [ZERO_LINE] * 4
    dashes = [cut_mark_line] * 4
    combined_lines = [LINE_ROW0, LINE_ROW127, *gap, *dashes, *gap, LINE_ROW0, LINE_ROW127]
    assert len(combined_lines) == 16  # 2 (img1) + 4 (gap) + 4 (cutmark) + 4 (gap) + 2 (img2)

    # Frame bytes are the hand-derived literals defined above (FRAME_ROW0_PB,
    # FRAME_ROW127_PB, ZERO_FRAME_PB, CUT_MARK_FRAME_PB) -- not computed via
    # encode_line -- concatenated in the same 2+4+4+4+2 line order asserted above.
    combined_frames = (
        FRAME_ROW0_PB
        + FRAME_ROW127_PB
        + ZERO_FRAME_PB * 4
        + CUT_MARK_FRAME_PB * 4
        + ZERO_FRAME_PB * 4
        + FRAME_ROW0_PB
        + FRAME_ROW127_PB
    )

    z_16lines = b"\x1b\x69\x7a\x84\x00\x18\x00\x10\x00\x00\x00\x00\x00"
    preamble = (
        b"\x00" * 100
        + b"\x1b\x40"
        + b"\x1b\x69\x61\x01"
        + b"\x1b\x69\x4d\x40"
        + b"\x1b\x69\x4b\x00"  # STRIP_MARKS -> no-chain bit CLEAR
        + b"\x1b\x69\x64\x0e\x00"
        + b"\x4d\x02"
    )
    expected = preamble + z_16lines + combined_frames + CTRL_Z
    assert result.data == expected
    assert result.page_count == 1
    assert result.total_raster_lines == 16


# --- 6. 12mm tape ESC i z: n3 == 0x0C; margin 3mm -> mm_to_dots(3)=21=0x15 ---


def test_12mm_tape_esc_i_z_and_margin():
    strategy = ClassicStrategy()
    opts = JobOptions(chain_mode=ChainMode.CHAIN_FF, margin_mm=3.0)
    img = Image.new("1", (1, 70), 1)  # 12mm print_dots=70, 1 blank column
    result = build_job([img], TAPE_12MM, strategy, opts)

    z_idx = result.data.index(b"\x1b\x69\x7a")
    assert result.data[z_idx + 5] == 0x0C  # n3: 12mm status width byte

    d_idx = result.data.index(b"\x1b\x69\x64")
    assert result.data[d_idx + 3 : d_idx + 5] == b"\x15\x00"  # margin dots LE


# --- 11. Errors ---


def test_build_job_empty_images_raises():
    strategy = ClassicStrategy()
    opts = JobOptions()
    with pytest.raises(ValueError):
        build_job([], TAPE_24MM, strategy, opts)


def test_build_job_mixed_heights_raises():
    strategy = ClassicStrategy()
    opts = JobOptions()
    good = Image.new("1", (1, 128), 1)  # matches TAPE_24MM.print_dots
    bad = Image.new("1", (1, 70), 1)  # wrong height for TAPE_24MM
    with pytest.raises(ValueError):
        build_job([good, bad], TAPE_24MM, strategy, opts)


def test_build_job_mixed_heights_raises_strip_marks():
    strategy = ClassicStrategy()
    opts = JobOptions(chain_mode=ChainMode.STRIP_MARKS)
    good = Image.new("1", (1, 128), 1)
    bad = Image.new("1", (1, 70), 1)
    with pytest.raises(ValueError):
        build_job([good, bad], TAPE_24MM, strategy, opts)
