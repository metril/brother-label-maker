"""Table-driven tests for labelmaker.driver.geometry.

Tape dimension figures are taken verbatim from Brother's official raster
manual for the PT-E550W/P750W/P710BT family (128-pin/180dpi head, shared by
the PT-E720BT; see docs/hardware-probe-notes.md's References section for the download link)
and cross-checked against docs/research/features.md's tape geometry tables.
"""

import pytest

from labelmaker.driver.geometry import (
    HEAD_PINS,
    MARGIN_MAX_MM,
    MARGIN_MIN_MM,
    MIN_FEED_MM,
    MediaFamily,
    all_tapes,
    clamp_margin_mm,
    dots_to_mm,
    find_tape,
    min_job_length_mm,
    mm_to_dots,
)

# --- Table data (nominal_mm, total_dots, print_dots, left_pin) ---

TZE_ROWS = [
    (3.5, 24, 24, 52),
    (6, 42, 32, 48),
    (9, 64, 50, 39),
    (12, 84, 70, 29),
    (18, 128, 112, 8),
    (24, 170, 128, 0),
]

# (nominal_mm, total_dots, print_dots) -- left_pin is derived via the formula
HSE_2_1_ROWS = [
    (5.8, 40, 28),
    (8.8, 62, 48),
    (11.7, 82, 66),
    (17.7, 126, 106),
    (23.6, 168, 128),
]

HSE_3_1_ROWS = [
    (5.2, 36, 20),
    (9.0, 64, 44),
    (11.2, 80, 50),
    (21.0, 148, 120),
]


def _find(nominal_mm: float, family: MediaFamily):
    for tape in all_tapes():
        if tape.family is family and tape.nominal_mm == nominal_mm:
            return tape
    raise AssertionError(f"no tape in all_tapes() for {nominal_mm=} {family=}")


# --- 1. TZe table: total/print/left_pin exactly as tabled ---


@pytest.mark.parametrize("nominal_mm,total_dots,print_dots,left_pin", TZE_ROWS)
def test_tze_table_values(nominal_mm, total_dots, print_dots, left_pin):
    tape = _find(nominal_mm, MediaFamily.TZE)
    assert tape.total_dots == total_dots
    assert tape.print_dots == print_dots
    # tabled left_pin must equal the centering formula -- this proves the formula.
    assert left_pin == (HEAD_PINS - print_dots) // 2
    assert tape.left_pin == left_pin


# --- 2. HSe tables: print dots as tabled; left_pin via formula; max_length_mm == 500 ---


@pytest.mark.parametrize("nominal_mm,total_dots,print_dots", HSE_2_1_ROWS)
def test_hse_2_1_table_values(nominal_mm, total_dots, print_dots):
    tape = _find(nominal_mm, MediaFamily.HSE_2_1)
    assert tape.total_dots == total_dots
    assert tape.print_dots == print_dots
    assert tape.left_pin == (HEAD_PINS - print_dots) // 2
    assert tape.max_length_mm == 500.0


@pytest.mark.parametrize("nominal_mm,total_dots,print_dots", HSE_3_1_ROWS)
def test_hse_3_1_table_values(nominal_mm, total_dots, print_dots):
    tape = _find(nominal_mm, MediaFamily.HSE_3_1)
    assert tape.total_dots == total_dots
    assert tape.print_dots == print_dots
    assert tape.left_pin == (HEAD_PINS - print_dots) // 2
    assert tape.max_length_mm == 500.0


def test_tze_max_length_mm():
    assert _find(24, MediaFamily.TZE).max_length_mm == 1000.0


# --- 3. Pin invariant for ALL tapes ---


@pytest.mark.parametrize("tape", all_tapes(), ids=lambda t: f"{t.family.name}-{t.nominal_mm}")
def test_pin_invariant(tape):
    right = HEAD_PINS - tape.left_pin - tape.print_dots
    assert tape.left_pin >= 0
    assert right >= 0
    assert tape.left_pin + tape.print_dots + right == HEAD_PINS


def test_all_tapes_nonempty():
    assert len(all_tapes()) == len(TZE_ROWS) + len(HSE_2_1_ROWS) + len(HSE_3_1_ROWS)


# --- 4. mm <-> dots conversions ---


def test_mm_to_dots_min_feed():
    # 24.5 * (180/25.4) = 173.622... -> round-half-up -> 174
    assert mm_to_dots(24.5) == 174


def test_mm_to_dots_margin_min():
    assert mm_to_dots(2) == 14


def test_mm_to_dots_margin_max():
    # 127 * (180/25.4) == 900.0 exactly -- reproduces the manual's 900-dot figure.
    assert mm_to_dots(127) == 900


def test_dots_to_mm_round_trip():
    for dots in (14, 174, 900, 128, 24):
        mm = dots_to_mm(dots)
        assert abs(mm_to_dots(mm) - dots) <= 1


# --- 5. clamp_margin_mm ---


def test_clamp_margin_mm_below_range():
    assert clamp_margin_mm(0.5) == MARGIN_MIN_MM


def test_clamp_margin_mm_inside_range():
    assert clamp_margin_mm(10.0) == 10.0


def test_clamp_margin_mm_above_range():
    assert clamp_margin_mm(500.0) == MARGIN_MAX_MM


# --- 6. find_tape ---


def test_find_tape_hit_tze_24mm():
    tape = find_tape(24, MediaFamily.TZE)
    assert tape is not None
    assert tape.nominal_mm == 24
    assert tape.family is MediaFamily.TZE


def test_find_tape_hit_hse_2_1_9mm_status_width():
    tape = find_tape(9, MediaFamily.HSE_2_1)
    assert tape is not None
    assert tape.nominal_mm == 8.8
    assert tape.family is MediaFamily.HSE_2_1


def test_find_tape_miss_returns_none():
    assert find_tape(999, MediaFamily.TZE) is None


def test_find_tape_family_disambiguation_for_width_9():
    tze = find_tape(9, MediaFamily.TZE)
    hse_2_1 = find_tape(9, MediaFamily.HSE_2_1)
    hse_3_1 = find_tape(9, MediaFamily.HSE_3_1)

    assert tze is not None and tze.nominal_mm == 9 and tze.family is MediaFamily.TZE
    assert (
        hse_2_1 is not None and hse_2_1.nominal_mm == 8.8 and hse_2_1.family is MediaFamily.HSE_2_1
    )
    assert (
        hse_3_1 is not None and hse_3_1.nominal_mm == 9.0 and hse_3_1.family is MediaFamily.HSE_3_1
    )
    assert len({id(tze), id(hse_2_1), id(hse_3_1)}) == 3


# --- 7. min_job_length_mm ---


def test_min_job_length_mm_below_floor():
    assert min_job_length_mm(10.0) == MIN_FEED_MM


def test_min_job_length_mm_above_floor():
    assert min_job_length_mm(50.0) == 50.0


def test_min_job_length_mm_at_floor():
    assert min_job_length_mm(MIN_FEED_MM) == MIN_FEED_MM
