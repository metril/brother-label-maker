"""Tape and print-head geometry: the single source of truth for the driver/render stack.

Pure geometry -- no I/O, no USB. All figures are taken from Brother's official
raster manual for the PT-E550W/P750W/P710BT family; the PT-E720BT shares the
same 128-pin/180dpi head.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum, auto

HEAD_PINS = 128
DPI = 180
DOTS_PER_MM = DPI / 25.4

# Mechanical head-to-cutter gap: any label consumes at least this much tape.
MIN_FEED_MM = 24.5
# Minimum printable length (31 dots).
MIN_LABEL_MM = 4.4
# Printable margin bounds (14 dots / 900 dots @ 180dpi).
MARGIN_MIN_MM = 2.0
MARGIN_MAX_MM = 127.0


class MediaFamily(Enum):
    TZE = auto()
    HSE_2_1 = auto()
    HSE_3_1 = auto()


@dataclass(frozen=True)
class TapeSpec:
    nominal_mm: float
    family: MediaFamily
    total_dots: int
    print_dots: int
    status_width_mm: int  # integer mm reported by printer status byte 10

    @property
    def left_pin(self) -> int:
        return (HEAD_PINS - self.print_dots) // 2

    @property
    def max_length_mm(self) -> float:
        return 1000.0 if self.family is MediaFamily.TZE else 500.0


def mm_to_dots(mm: float) -> int:
    """Convert millimetres to dots, rounding half away from zero (round-half-up)."""
    dots = Decimal(str(mm)) * Decimal(DPI) / Decimal("25.4")
    return int(dots.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dots_to_mm(dots: int) -> float:
    return dots * 25.4 / DPI


def clamp_margin_mm(mm: float) -> float:
    return max(MARGIN_MIN_MM, min(MARGIN_MAX_MM, mm))


# --- Tape tables -------------------------------------------------------------
# (nominal_mm, total_dots, print_dots, status_width_mm)

_TZE_ROWS: tuple[tuple[float, int, int, int], ...] = (
    (3.5, 24, 24, 4),  # UNVERIFIED: confirm at physical checkpoint
    (6, 42, 32, 6),
    (9, 64, 50, 9),
    (12, 84, 70, 12),
    (18, 128, 112, 18),
    (24, 170, 128, 24),
)

# HSe status widths are all UNVERIFIED: confirm at physical checkpoint.
_HSE_2_1_ROWS: tuple[tuple[float, int, int, int], ...] = (
    (5.8, 40, 28, 6),
    (8.8, 62, 48, 9),
    (11.7, 82, 66, 12),
    (17.7, 126, 106, 18),
    (23.6, 168, 128, 24),
)

_HSE_3_1_ROWS: tuple[tuple[float, int, int, int], ...] = (
    (5.2, 36, 20, 5),
    (9.0, 64, 44, 9),
    (11.2, 80, 50, 11),
    (21.0, 148, 120, 21),
)

_ALL_TAPES: tuple[TapeSpec, ...] = tuple(
    TapeSpec(
        nominal_mm=nominal_mm,
        family=family,
        total_dots=total_dots,
        print_dots=print_dots,
        status_width_mm=status_width_mm,
    )
    for family, rows in (
        (MediaFamily.TZE, _TZE_ROWS),
        (MediaFamily.HSE_2_1, _HSE_2_1_ROWS),
        (MediaFamily.HSE_3_1, _HSE_3_1_ROWS),
    )
    for nominal_mm, total_dots, print_dots, status_width_mm in rows
)


def all_tapes() -> tuple[TapeSpec, ...]:
    return _ALL_TAPES


def find_tape(status_width_mm: int, family: MediaFamily = MediaFamily.TZE) -> TapeSpec | None:
    for tape in _ALL_TAPES:
        if tape.status_width_mm == status_width_mm and tape.family is family:
            return tape
    return None


def min_job_length_mm(label_length_mm: float) -> float:
    return max(label_length_mm, MIN_FEED_MM)
