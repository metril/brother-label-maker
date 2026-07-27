"""Supplement to test_job.py (golden -- may NOT be modified, see the
Phase 1 fix-wave-A brief's "driver test gaps" item, triage item 7).

test_job.py's E310BTStrategy coverage
(test_e310bt_single_page_full_stream, test_e310bt_chain_ff_two_pages_
magic_only_on_first_page) only exercises CHAIN_FF, where build_job's
_build_chained CHAIN_FF branch calls page_header(..., is_first=(i == 0)) --
MAGIC follows only the FIRST of a chained job's pages.

CUT_EACH is structurally different: _build_chained's CUT_EACH branch loops
per image, calling preamble(...) + page_header(..., True) + frames +
page_end(True) for EACH image independently -- i.e. every image gets its
own fresh preamble (its own FLUSH) and is ALWAYS treated as page_header's
"first page" (is_first=True unconditionally, not i == 0), so
E310BTStrategy's MAGIC (appended only when is_first) fires once PER IMAGE,
not once per build_job() call. That combination (e310bt x CUT_EACH x
multiple images) has no test anywhere -- this pins it: FLUSH exactly twice,
MAGIC exactly twice, for 2 images.

Expected bytes are hand-derived entirely per test_job.py's own conventions
(hand-computed protocol-byte + frame-byte literals, never obtained by
calling the code under test -- see test_job.py's module docstring and
derivation comments); the MAGIC/CTRL_Z byte constants are imported from
strategies.py as plain protocol constants, exactly like test_job.py itself
does (`from labelmaker.driver.strategies import CTRL_Z, FF, MAGIC`), not
computed.
"""

from PIL import Image

from labelmaker.driver.geometry import MediaFamily, find_tape
from labelmaker.driver.job import ChainMode, JobOptions, build_job
from labelmaker.driver.raster import BYTES_PER_LINE
from labelmaker.driver.strategies import CTRL_Z, MAGIC, E310BTStrategy

TAPE_24MM = find_tape(24, MediaFamily.TZE)  # left_pin=0, print_dots=128
assert TAPE_24MM is not None and TAPE_24MM.left_pin == 0 and TAPE_24MM.print_dots == 128


def _blank_line(index: int, mask: int) -> bytes:
    line = bytearray(BYTES_PER_LINE)
    line[index] = mask
    return bytes(line)


def _one_col_image(black_row: int) -> Image.Image:
    img = Image.new("1", (1, 128), 1)
    img.putpixel((0, black_row), 0)
    return img


# --- Hand-derived pin lines (same derivation as test_job.py's LINE_ROW0/127) ---
# col black at row0   -> pin left_pin+print_dots-1-0   = 127 -> byte15, mask 0x01
# col black at row127 -> pin left_pin+print_dots-1-127 = 0   -> byte0,  mask 0x80
LINE_ROW0 = _blank_line(15, 0x01)
LINE_ROW127 = _blank_line(0, 0x80)

# RAW frame format (raster.py docstring): 0x47 + LE u16 length(=16) + the 16
# raw pin bytes verbatim.
FRAME_ROW0_RAW = b"\x47\x10\x00" + b"\x00" * 15 + b"\x01"
FRAME_ROW127_RAW = b"\x47\x10\x00" + b"\x80" + b"\x00" * 15

# ESC i z params, 1 raster line, 24mm tape: n1=PI_VALIDITY=0x84, n2=0x00,
# n3=tape.status_width_mm=0x18(24), n4=0x00, n5-n8=LE u32(1), n9=n10=0x00.
ESC_I_Z_1LINE_24MM = b"\x1b\x69\x7a\x84\x00\x18\x00\x01\x00\x00\x00\x00\x00"

# E310BTStrategy.preamble (strategies.py): FLUSH + ESC @ + ESC i a 01 +
# ESC i K <no-chain bit>. CUT_EACH -> _no_chain(options)=True -> ESC i K's
# bit 0x08 SET (no-chain: feed+cut per label).
PREAMBLE_CUT_EACH = (
    b"\x00" * 100  # FLUSH
    + b"\x1b\x40"  # ESC @ (ESC_INIT)
    + b"\x1b\x69\x61\x01"  # ESC i a 01 (raster mode select)
    + b"\x1b\x69\x4b\x08"  # ESC i K, no-chain bit SET
)


def test_e310bt_cut_each_two_images_full_stream():
    strategy = E310BTStrategy()
    opts = JobOptions(chain_mode=ChainMode.CUT_EACH, margin_mm=2.0)
    img_a = _one_col_image(black_row=0)
    img_b = _one_col_image(black_row=127)
    result = build_job([img_a, img_b], TAPE_24MM, strategy, opts)

    # CUT_EACH: each image is its own independent "job" -- fresh preamble
    # (own FLUSH), page_header (is_first=True always -> MAGIC every time),
    # frames, then CTRL_Z (is_last=True always, never FF -- no chaining).
    expected = (
        PREAMBLE_CUT_EACH
        + ESC_I_Z_1LINE_24MM
        + MAGIC
        + FRAME_ROW0_RAW
        + CTRL_Z
        + PREAMBLE_CUT_EACH
        + ESC_I_Z_1LINE_24MM
        + MAGIC
        + FRAME_ROW127_RAW
        + CTRL_Z
    )
    assert result.data == expected
    assert result.data.count(b"\x00" * 100) == 2  # FLUSH exactly twice
    assert result.data.count(MAGIC) == 2  # MAGIC exactly twice -- once per image
    assert b"\x0c" not in result.data  # FF (chain) must never appear in CUT_EACH
    assert result.page_count == 2
    assert result.total_raster_lines == 2
    assert result.strategy_name == "e310bt"
    assert result.chain_mode is ChainMode.CUT_EACH
