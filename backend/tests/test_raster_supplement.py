"""Supplement to test_raster.py (golden -- may NOT be modified, see the
Phase 1 fix-wave-A brief's "driver test gaps" item, triage item 7).

test_raster.py's RAW-compression coverage is limited to the all-zero line
(test_encode_line_zero_raw): 0x47 + LE u16 length + 16 zero bytes. It never
exercises RAW framing for a line with actual set bits -- unlike PACKBITS,
RAW has no special-case branch (see raster.py's encode_line: the RAW arm is
just `payload = bytes(pins)`, verbatim, no all-zero special case), so this
is a coverage gap rather than a suspected bug, but a real gap: a regression
that broke RAW's non-zero path specifically (e.g. an accidental truncation
or byte-order flip introduced only in that branch) would slip past
test_raster.py entirely.

Expected bytes are hand-derived exactly per test_raster.py's own
conventions (hand-computed literals, never obtained by calling the code
under test) -- see its module docstring and derivation comments.
"""

from labelmaker.driver.raster import BYTES_PER_LINE, Compression, encode_line

# A single-pixel pin line: one bit set in the LAST byte (index 15, bit 0 --
# mask 0x01), every other byte zero. This is the exact line a 24mm-tape
# top-row black pixel encodes to (see test_raster.py's
# test_single_pixel_24mm_top_row: pin 127 -> byte 127//8=15, MSB_FIRST bit
# 7-(127%8)=0 -> mask 0x01) -- reused here as "the known single-pixel line"
# named in the brief, re-derived independently rather than imported from
# test_raster.py (which is golden and shouldn't gain new dependents).
_SINGLE_PIXEL_LINE = (b"\x00" * (BYTES_PER_LINE - 1)) + b"\x01"


def test_encode_line_raw_single_pixel_line():
    # RAW framing (raster.py's module docstring): 0x47 ('G') + LE u16
    # payload length (16 = 0x0010, i.e. bytes 0x10 0x00) + the 16 raw pin
    # bytes verbatim -- no RLE, no 'Z' all-zero shorthand (RAW never emits
    # it; that's PACKBITS-only, per raster.py's framing docstring).
    assert len(_SINGLE_PIXEL_LINE) == BYTES_PER_LINE
    assert encode_line(_SINGLE_PIXEL_LINE, Compression.RAW) == (
        b"\x47\x10\x00" + _SINGLE_PIXEL_LINE
    )
