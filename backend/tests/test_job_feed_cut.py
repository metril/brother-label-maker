"""Tests for labelmaker.driver.job's feed-cut trigger job (task: feed & cut
trigger, docs/superpowers/specs/2026-08-04-feed-cut-trigger-design.md):
feed_cut_image, feed_cut_options, build_feed_cut_job.

New coverage lives in this separate file rather than test_job.py itself --
test_job.py's own module docstring/test_job_supplement.py's header both
establish that test_job.py is a frozen golden reference (see
test_job_supplement.py: "Supplement to test_job.py (golden -- may NOT be
modified...)"). Same discipline as test_job.py/test_job_supplement.py
otherwise: expected byte literals below are assembled entirely by hand
(protocol-byte constants from docs/hardware-probe-notes.md's protocol
quick-reference plus frame-byte literals whose PackBits/RAW derivation is
commented at the point of definition), never obtained by calling
raster.encode_line/build_job (the code under test) to produce an
expectation.
"""

from PIL import Image

from labelmaker.driver.geometry import MARGIN_MIN_MM, MediaFamily, find_tape, mm_to_dots
from labelmaker.driver.job import (
    ChainMode,
    JobOptions,
    build_feed_cut_job,
    feed_cut_image,
    feed_cut_options,
)
from labelmaker.driver.strategies import CTRL_Z, MAGIC, ClassicStrategy, E310BTStrategy

TAPE_24MM = find_tape(24, MediaFamily.TZE)  # left_pin=0, print_dots=128
TAPE_12MM = find_tape(12, MediaFamily.TZE)  # left_pin=29, print_dots=70
assert TAPE_24MM is not None and TAPE_24MM.print_dots == 128
assert TAPE_12MM is not None

# ESC i z params for a 1-line/24mm page: n1=0x84, n2=0x00, n3=0x18(24),
# n4=0x00, n5-n8=1 (LE u32 = 01 00 00 00), n9=0x00, n10=0x00 -- same literal
# test_job.py's own ESC_I_Z_1LINE_24MM uses.
ESC_I_Z_1LINE_24MM = b"\x1b\x69\x7a\x84\x00\x18\x00\x01\x00\x00\x00\x00\x00"

# PACKBITS all-zero-line shorthand (raster.py's documented 'Z' == 0x5A) --
# a direct protocol fact, not a PackBits computation.
ZERO_FRAME_PB = b"Z"

# RAW frame format (raster.py docstring): 0x47 + LE u16 length(=16) + the 16
# raw (all-zero) pin bytes verbatim -- RAW has no 'Z' shorthand.
ZERO_FRAME_RAW = b"\x47\x10\x00" + b"\x00" * 16


# --- 1. feed_cut_image / feed_cut_options: the building blocks -------------


def test_feed_cut_image_is_one_dot_wide_tape_height_all_white():
    for tape in (TAPE_24MM, TAPE_12MM):
        img = feed_cut_image(tape)
        assert img.mode == "1"
        assert img.size == (1, tape.print_dots)
        pixels = img.load()
        assert all(pixels[0, y] == 1 for y in range(tape.print_dots))  # 1 == white


def test_feed_cut_options_fixed_values():
    assert feed_cut_options() == JobOptions(
        auto_cut=True, chain_mode=ChainMode.CUT_EACH, margin_mm=MARGIN_MIN_MM
    )


def test_feed_cut_minimized_margin_resolves_to_margin_min_mm_14_dots():
    # "minimized margins" (the design doc's phrasing) resolves to exactly
    # geometry.MARGIN_MIN_MM (2.0mm) -- clamp_margin_mm's own floor -- which
    # mm_to_dots rounds to 14 dots, the same value JobOptions' own plain
    # default (margin_mm=2.0) already produces.
    assert feed_cut_options().margin_mm == MARGIN_MIN_MM
    assert mm_to_dots(MARGIN_MIN_MM) == 14


# --- 2. build_feed_cut_job: golden bytes, classic/24mm ----------------------
#
# CUT_EACH, single 1-dot-wide all-white image -> _build_chained's CUT_EACH
# branch: one preamble, one page_header(n_lines=1, is_first=True), one
# all-zero frame, page_end(is_last=True) == CTRL_Z.


def test_build_feed_cut_job_classic_24mm_golden_bytes():
    strategy = ClassicStrategy()
    result = build_feed_cut_job(TAPE_24MM, strategy)

    preamble = (
        b"\x00" * 100  # FLUSH
        + b"\x1b\x40"  # ESC_INIT
        + b"\x1b\x69\x61\x01"  # ESC_RASTER_MODE
        + b"\x1b\x69\x4d\x40"  # ESC i M -- auto-cut ON
        + b"\x1b\x69\x4b\x08"  # ESC i K -- CUT_EACH -> no-chain bit SET
        + b"\x1b\x69\x64\x0e\x00"  # ESC i d -- margin_mm=2.0 -> mm_to_dots=14=0x0e, LE
        + b"\x4d\x02"  # M 02 -- select PackBits
    )
    expected = preamble + ESC_I_Z_1LINE_24MM + ZERO_FRAME_PB + CTRL_Z

    assert result.data == expected
    assert result.page_count == 1
    assert result.total_raster_lines == 1
    assert result.strategy_name == "classic"
    assert result.chain_mode is ChainMode.CUT_EACH


# --- 3. build_feed_cut_job: golden bytes, e310bt/24mm -----------------------
#
# E310BTStrategy's preamble has no ESC i M (no auto-cut byte at all -- see
# strategies.py/test_job.py's own e310bt tests) and no margin/PackBits-select
# bytes; MAGIC follows the single page's ESC i z (CUT_EACH's is_first is
# always True per _build_chained -- see test_job_supplement.py's own note on
# this); frames are RAW (no 'Z' shorthand).
#
# UNVERIFIED risk (fix wave item 2, see build_feed_cut_job's own docstring
# in driver/job.py for the full writeup): this golden byte stream is
# EXACTLY what e310bt would send today, no ESC i M anywhere -- it proves the
# bytes are what the strategy produces, NOT that those bytes actually cut on
# real e310bt hardware. If the real firmware needs the auto-cut bit (which
# this strategy never sets, on any job, not just feed-cut) in addition to
# ESC i K's no-chain bit to fire the blade, a feed-cut job under this
# strategy would feed ~24.5mm and report "done" while never cutting --
# silently. Do not "fix" this test by adding bytes; confirm against
# hardware first (docs/project-handoff.md's checkpoint-2 list).


def test_build_feed_cut_job_e310bt_24mm_golden_bytes():
    strategy = E310BTStrategy()
    result = build_feed_cut_job(TAPE_24MM, strategy)

    preamble = (
        b"\x00" * 100  # FLUSH
        + b"\x1b\x40"  # ESC_INIT
        + b"\x1b\x69\x61\x01"  # ESC_RASTER_MODE
        + b"\x1b\x69\x4b\x08"  # ESC i K -- CUT_EACH -> no-chain bit SET
    )
    expected = preamble + ESC_I_Z_1LINE_24MM + MAGIC + ZERO_FRAME_RAW + CTRL_Z

    assert result.data == expected
    assert MAGIC[5] == 0x4D
    assert result.strategy_name == "e310bt"
    assert result.chain_mode is ChainMode.CUT_EACH


# --- 4. Different tape width: n3 byte tracks status_width_mm, not hardcoded --


def test_build_feed_cut_job_12mm_tape_esc_i_z_n3_byte():
    strategy = ClassicStrategy()
    result = build_feed_cut_job(TAPE_12MM, strategy)

    z_idx = result.data.index(b"\x1b\x69\x7a")
    assert result.data[z_idx + 5] == 0x0C  # n3: 12mm status width byte
    assert result.data.endswith(ZERO_FRAME_PB + CTRL_Z)
    # image is sized to TAPE_12MM.print_dots, not TAPE_24MM's -- proven
    # indirectly: build_job would have raised ValueError on a height
    # mismatch (raster.py's image_to_pin_lines) if feed_cut_image hadn't
    # sized itself off the SAME tape passed to build_feed_cut_job.
    assert isinstance(feed_cut_image(TAPE_12MM), Image.Image)
