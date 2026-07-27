"""Tests for labelmaker.driver.strategies: the two candidate init/print
strategies (classic PackBits vs. e310bt-family RAW/magic). These byte streams
are what the physical checkpoint A/B-tests against the real printer, so every
expected literal below is hand-computed (see derivation comments) against
protocol facts in HANDOFF.md's protocol quick-reference, Brother's family
raster manual for the PT-E550W/P750W/P710BT (see HANDOFF.md's References
section for the download link), and docs/research/protocol.md's fork
findings (the e310bt `MAGIC` packet and its command ordering) -- never
obtained by calling the code under test. `geometry.py` and `raster.py` are
already-merged, independently-tested dependencies used here as trusted
oracles (e.g. `mm_to_dots`, `find_tape`).
"""

import pytest

from labelmaker.driver.geometry import MediaFamily, clamp_margin_mm, find_tape, mm_to_dots
from labelmaker.driver.job import ChainMode, JobOptions
from labelmaker.driver.raster import Compression
from labelmaker.driver.strategies import (
    CTRL_Z,
    FF,
    FLUSH,
    MAGIC,
    ClassicStrategy,
    E310BTStrategy,
)

TAPE_24MM = find_tape(24, MediaFamily.TZE)
TAPE_12MM = find_tape(12, MediaFamily.TZE)
assert TAPE_24MM is not None and TAPE_12MM is not None


def _opts(**kwargs) -> JobOptions:
    return JobOptions(**kwargs)


# --- Shared protocol byte constants (hand-derived from the brief's tables) ---
# FLUSH = 100 x 0x00; ESC @ = 1B 40; ESC i a 01 = 1B 69 61 01
# ESC i M n = 1B 69 4D n (bit 0x40 = auto-cut)
# ESC i K n = 1B 69 4B n (bit 0x08 = no-chain)
# ESC i d n1 n2 = 1B 69 64 n1 n2 (margin dots, LE u16)
# M 02 = 4D 02
# ESC i z = 1B 69 7A 84 00 <width_mm> 00 <n_lines LE u32> 00 00
# MAGIC = 1B 69 64 01 00 4D 00 (byte index 5 == 0x4D)


def test_flush_ff_ctrlz_magic_constants():
    assert FLUSH == b"\x00" * 100
    assert FF == b"\x0c"
    assert CTRL_Z == b"\x1a"
    assert MAGIC == b"\x1b\x69\x64\x01\x00\x4d\x00"
    assert MAGIC[5] == 0x4D


# --- page_end: shared implementation on the ABC, FF unless last, else CTRL_Z ---


def test_page_end_classic():
    s = ClassicStrategy()
    assert s.page_end(is_last=False) == FF
    assert s.page_end(is_last=True) == CTRL_Z


def test_page_end_e310bt():
    s = E310BTStrategy()
    assert s.page_end(is_last=False) == FF
    assert s.page_end(is_last=True) == CTRL_Z


# --- Classic preamble: FLUSH + ESC @ + ESC i a 01 + ESC i M + ESC i K + ESC i d + M02 ---


def test_classic_preamble_full_layout_auto_cut_on_chain_ff():
    s = ClassicStrategy()
    opts = _opts(chain_mode=ChainMode.CHAIN_FF, auto_cut=True, margin_mm=2.0)
    out = s.preamble(TAPE_24MM, opts)
    # margin 2.0mm -> mm_to_dots(2) = 14 = 0x0E -> LE 0x0E 0x00 (verified against
    # geometry.py directly, a trusted merged dependency, not the code under test)
    assert mm_to_dots(clamp_margin_mm(2.0)) == 14
    expected = (
        b"\x00" * 100
        + b"\x1b\x40"
        + b"\x1b\x69\x61\x01"
        + b"\x1b\x69\x4d\x40"  # auto_cut True -> 0x40
        + b"\x1b\x69\x4b\x00"  # CHAIN_FF -> chain bit CLEAR
        + b"\x1b\x69\x64\x0e\x00"
        + b"\x4d\x02"
    )
    assert out == expected


def test_classic_preamble_auto_cut_off():
    s = ClassicStrategy()
    opts = _opts(chain_mode=ChainMode.CHAIN_FF, auto_cut=False)
    out = s.preamble(TAPE_24MM, opts)
    idx = out.index(b"\x1b\x69\x4d")
    assert out[idx : idx + 4] == b"\x1b\x69\x4d\x00"  # ESC i M byte == 0x00


@pytest.mark.parametrize(
    "chain_mode,expected_bit",
    [
        (ChainMode.CUT_EACH, 0x08),
        (ChainMode.CHAIN_FF, 0x00),
        (ChainMode.STRIP_MARKS, 0x00),
    ],
)
def test_classic_esc_i_k_mapping(chain_mode, expected_bit):
    s = ClassicStrategy()
    opts = _opts(chain_mode=chain_mode)
    out = s.preamble(TAPE_24MM, opts)
    idx = out.index(b"\x1b\x69\x4b")
    assert out[idx : idx + 3] == b"\x1b\x69\x4b"
    assert out[idx + 3] == expected_bit


@pytest.mark.parametrize(
    "chain_mode,expected_bit",
    [
        (ChainMode.CUT_EACH, 0x08),
        (ChainMode.CHAIN_FF, 0x00),
        (ChainMode.STRIP_MARKS, 0x00),
    ],
)
def test_e310bt_esc_i_k_mapping(chain_mode, expected_bit):
    s = E310BTStrategy()
    opts = _opts(chain_mode=chain_mode)
    out = s.preamble(TAPE_24MM, opts)
    expected = (
        b"\x00" * 100 + b"\x1b\x40" + b"\x1b\x69\x61\x01" + b"\x1b\x69\x4b" + bytes([expected_bit])
    )
    assert out == expected


@pytest.mark.parametrize("margin_mm,expected_dots_le", [(0.5, b"\x0e\x00"), (200, b"\x84\x03")])
def test_classic_margin_clamp(margin_mm, expected_dots_le):
    # 0.5mm clamps to MARGIN_MIN_MM=2.0 -> mm_to_dots(2)=14=0x0E -> LE 0e 00
    # 200mm clamps to MARGIN_MAX_MM=127.0 -> mm_to_dots(127)=900=0x0384 -> LE 84 03
    s = ClassicStrategy()
    opts = _opts(margin_mm=margin_mm)
    out = s.preamble(TAPE_24MM, opts)
    # ESC i d n1 n2 is the 2 bytes right after "\x1b\x69\x64"
    idx = out.index(b"\x1b\x69\x64")
    assert out[idx + 3 : idx + 5] == expected_dots_le


# --- E310BT preamble: FLUSH + ESC @ + ESC i a 01 + ESC i K -- NO ESC i M, NO ESC i d, NO magic ---


def test_e310bt_preamble_excludes_m_and_d_and_magic():
    s = E310BTStrategy()
    opts = _opts(chain_mode=ChainMode.CHAIN_FF, auto_cut=True, margin_mm=2.0)
    out = s.preamble(TAPE_24MM, opts)
    assert b"\x1b\x69\x4d" not in out  # no ESC i M
    assert b"\x1b\x69\x64" not in out  # no ESC i d / magic (magic moved to page_header)
    assert b"\x4d\x02" not in out  # no M 02 (PackBits select)
    assert out == b"\x00" * 100 + b"\x1b\x40" + b"\x1b\x69\x61\x01" + b"\x1b\x69\x4b\x00"


# --- ESC i z 10-byte layout (both strategies share this) ---
# n1=0x84 (PI_RECOVER|PI_WIDTH), n2=0x00, n3=status_width_mm, n4=0x00,
# n5-n8=n_lines LE u32, n9=0x00, n10=0x00


def test_classic_page_header_24mm():
    s = ClassicStrategy()
    out = s.page_header(TAPE_24MM, n_lines=2, is_first=True)
    assert out == b"\x1b\x69\x7a\x84\x00\x18\x00\x02\x00\x00\x00\x00\x00"


def test_classic_page_header_12mm_width_byte():
    s = ClassicStrategy()
    out = s.page_header(TAPE_12MM, n_lines=1, is_first=True)
    assert out[5] == 0x0C  # n3 = 12 decimal = 0x0C


def test_classic_page_header_ignores_is_first():
    s = ClassicStrategy()
    assert s.page_header(TAPE_24MM, 2, True) == s.page_header(TAPE_24MM, 2, False)


def test_page_header_raster_count_wide_le_u32():
    # 300-column page -> n5-n8 = 300 as LE u32 = 2c 01 00 00
    s = ClassicStrategy()
    out = s.page_header(TAPE_24MM, n_lines=300, is_first=True)
    assert out[7:11] == b"\x2c\x01\x00\x00"


# --- E310BT page_header: MAGIC follows ESC i z, only on the first page ---
# (deliberate deviation resolution: the naive preamble = ...K + MAGIC would
# yield K, MAGIC, z for page 1, which contradicts the researched K, z, magic
# order; per the brief, preamble ends after K, and page_header(is_first=True)
# appends MAGIC after ESC i z instead.)
# UNVERIFIED: magic placement on chained pages (page_header(is_first=False)
# omits magic entirely -- not independently confirmed against hardware).


def test_e310bt_page_header_first_page_includes_magic_after_z():
    s = E310BTStrategy()
    out = s.page_header(TAPE_24MM, n_lines=2, is_first=True)
    z = b"\x1b\x69\x7a\x84\x00\x18\x00\x02\x00\x00\x00\x00\x00"
    assert out == z + MAGIC


def test_e310bt_page_header_non_first_page_omits_magic():
    s = E310BTStrategy()
    out = s.page_header(TAPE_24MM, n_lines=2, is_first=False)
    z = b"\x1b\x69\x7a\x84\x00\x18\x00\x02\x00\x00\x00\x00\x00"
    assert out == z
    assert MAGIC not in out


# --- compression / name attributes ---


def test_classic_attributes():
    s = ClassicStrategy()
    assert s.name == "classic"
    assert s.compression is Compression.PACKBITS


def test_e310bt_attributes():
    s = E310BTStrategy()
    assert s.name == "e310bt"
    assert s.compression is Compression.RAW
