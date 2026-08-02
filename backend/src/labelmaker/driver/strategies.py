"""Init/print strategies: the two candidate byte-stream families this printer
might require. The physical checkpoint A/B-tests these against the real
device -- each must be byte-perfect against its documented reference.

Protocol tables: docs/hardware-probe-notes.md's protocol quick-reference (flush/`ESC @`/
`ESC i a`/`ESC i z`/`ESC i M`/`ESC i d`/`M 02` command bytes) and Brother's
family raster manual for the PT-E550W/P750W/P710BT (see docs/hardware-probe-notes.md's
References section for the download link). The e310bt `MAGIC` packet and its
deliberate ordering deviation (K -> z -> magic, not the naive preamble
reading) come from docs/research/protocol.md's driver-landscape findings on
the e-control-systems/ptouch-print fork.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING

from labelmaker.driver.geometry import TapeSpec, clamp_margin_mm, mm_to_dots
from labelmaker.driver.protocol import ESC_INIT, FLUSH, ChainMode
from labelmaker.driver.raster import Compression

if TYPE_CHECKING:
    from labelmaker.driver.job import JobOptions

ESC_RASTER_MODE = b"\x1b\x69\x61\x01"
FF = b"\x0c"
CTRL_Z = b"\x1a"
SELECT_PACKBITS = b"\x4d\x02"
# 7-byte D460BT-magic packet (e310bt only). Byte index 5 MUST be 0x4D or the
# print gets corrupted, per the e-control-systems fork's inline comment.
MAGIC = b"\x1b\x69\x64\x01\x00\x4d\x00"

_PI_VALIDITY = 0x84  # PI_RECOVER 0x80 | PI_WIDTH 0x04
# UNVERIFIED: manual may define n9 as 0/1/2 for first/middle/last page --
# using 0x00 always, per docs/hardware-probe-notes.md's decoded example.
_ESC_I_Z_N9 = 0x00
_ESC_I_Z_N10 = 0x00


def _esc_i_z(tape: TapeSpec, n_lines: int) -> bytes:
    return (
        b"\x1b\x69\x7a"
        + bytes([_PI_VALIDITY, 0x00, tape.status_width_mm, 0x00])
        + n_lines.to_bytes(4, "little")
        + bytes([_ESC_I_Z_N9, _ESC_I_Z_N10])
    )


def _esc_i_k(no_chain: bool) -> bytes:
    # bit 0x08 = NO-chain (1 = feed+cut per label; 0 = chain).
    # UNVERIFIED: assumed same bit3 semantics on e310bt as classic.
    return b"\x1b\x69\x4b" + bytes([0x08 if no_chain else 0x00])


def _no_chain(options: JobOptions) -> bool:
    return options.chain_mode is ChainMode.CUT_EACH


class InitStrategy(ABC):
    name: str
    compression: Compression

    @abstractmethod
    def preamble(self, tape: TapeSpec, options: JobOptions) -> bytes:
        """Everything before the first page's raster data, except the per-page ESC i z."""

    @abstractmethod
    def page_header(self, tape: TapeSpec, n_lines: int, is_first: bool) -> bytes: ...

    def page_end(self, is_last: bool) -> bytes:
        return CTRL_Z if is_last else FF


class ClassicStrategy(InitStrategy):
    """FLUSH, ESC @, ESC i a 01, ESC i M, ESC i K, ESC i d, M 02 -- then ESC i z per page.

    # UNVERIFIED: command order -- docs/hardware-probe-notes.md documents the
    # flow z -> M -> d -> M02
    # for one page; we instead emit job-level M/K/d/M02 in the preamble and z
    # per page (z after M/K/d, not before). Tolerated by firmware per family
    # drivers per research; confirm at the physical checkpoint.
    """

    name = "classic"
    compression = Compression.PACKBITS

    def preamble(self, tape: TapeSpec, options: JobOptions) -> bytes:
        margin_dots = mm_to_dots(clamp_margin_mm(options.margin_mm))
        return (
            FLUSH
            + ESC_INIT
            + ESC_RASTER_MODE
            + b"\x1b\x69\x4d"
            + bytes([0x40 if options.auto_cut else 0x00])
            + _esc_i_k(_no_chain(options))
            + b"\x1b\x69\x64"
            + margin_dots.to_bytes(2, "little")
            + SELECT_PACKBITS
        )

    def page_header(self, tape: TapeSpec, n_lines: int, is_first: bool) -> bytes:
        return _esc_i_z(tape, n_lines)


class E310BTStrategy(InitStrategy):
    """FLUSH, ESC @, ESC i a 01, ESC i K -- no ESC i M, no ESC i d margin (MAGIC
    replaces it, appended after the first page's ESC i z instead of in the
    preamble, per the researched K -> z -> magic order; see brief for the
    deliberate deviation from the naive preamble = ...K + MAGIC reading).
    """

    name = "e310bt"
    compression = Compression.RAW

    def preamble(self, tape: TapeSpec, options: JobOptions) -> bytes:
        return FLUSH + ESC_INIT + ESC_RASTER_MODE + _esc_i_k(_no_chain(options))

    def page_header(self, tape: TapeSpec, n_lines: int, is_first: bool) -> bytes:
        # UNVERIFIED: magic placement on chained pages -- magic follows ESC i z
        # only on the first page; subsequent chained pages omit it.
        header = _esc_i_z(tape, n_lines)
        if is_first:
            header += MAGIC
        return header


# --- Public strategy registry (Task 1.3a) -----------------------------------
# Replaces cli.py's former private `_STRATEGIES` -- the CLI and (later) the
# web app both resolve a strategy by name through here.

STRATEGIES: dict[str, Callable[[], InitStrategy]] = {
    "classic": ClassicStrategy,
    "e310bt": E310BTStrategy,
}


def get_strategy(name: str) -> InitStrategy:
    """Look up and instantiate a strategy by name.

    Raises KeyError (message lists the valid names) for an unknown name.
    """
    try:
        return STRATEGIES[name]()
    except KeyError:
        raise KeyError(
            f"unknown strategy {name!r}; valid strategies: {sorted(STRATEGIES)}"
        ) from None
