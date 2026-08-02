"""Tests for labelmaker.driver.raster: 1-bit image -> per-column raster line frames.

All expected byte literals below are hand-computed (see derivation comments), never
obtained by calling the code under test. Protocol facts (raster line framing,
PackBits/RAW encoding, the 'Z' all-zero shorthand) come from docs/hardware-probe-notes.md's
protocol quick-reference and Brother's family raster manual for the
PT-E550W/P750W/P710BT (see docs/hardware-probe-notes.md's References section for the download
link); tape geometry figures come from docs/research/features.md's tape
geometry tables.
"""

import packbits
import pytest
from PIL import Image

from labelmaker.driver.geometry import MediaFamily, TapeSpec, all_tapes, find_tape
from labelmaker.driver.raster import (
    BYTES_PER_LINE,
    ZERO_LINE,
    BitOrder,
    Compression,
    RasterConfig,
    encode_image,
    encode_line,
    image_to_pin_lines,
)

TAPE_24MM = find_tape(24, MediaFamily.TZE)  # left_pin=0, print_dots=128
TAPE_12MM = find_tape(12, MediaFamily.TZE)  # left_pin=29, print_dots=70

assert TAPE_24MM is not None and TAPE_24MM.left_pin == 0 and TAPE_24MM.print_dots == 128
assert TAPE_12MM is not None and TAPE_12MM.left_pin == 29 and TAPE_12MM.print_dots == 70


def _blank_line(index: int, mask: int) -> bytes:
    """A 16-byte all-zero line with a single byte set to `mask` at `index`."""
    line = bytearray(BYTES_PER_LINE)
    line[index] = mask
    return bytes(line)


def _white_image(height: int) -> Image.Image:
    return Image.new("1", (1, height), 1)  # fill=1 -> all pixels white (255/nonzero)


def _black_image(height: int) -> Image.Image:
    return Image.new("1", (1, height), 0)  # fill=0 -> all pixels black


# --- 1. Single-pixel placement, 24mm tape (left_pin=0, print_dots=128) ---
#
# Default pin direction: row 0 (top) -> pin left_pin + print_dots - 1 = 127.
# pin 127 -> byte 127//8=15, MSB_FIRST bit 7-(127%8)=7-7=0 -> mask 0x01.
#
# Bottom row (127) -> pin left_pin = 0.
# pin 0 -> byte 0//8=0, MSB_FIRST bit 7-(0%8)=7 -> mask 0x80.


def test_single_pixel_24mm_top_row():
    img = _white_image(128)
    img.putpixel((0, 0), 0)  # black at row 0
    lines = image_to_pin_lines(img, TAPE_24MM)
    assert len(lines) == 1
    assert lines[0] == _blank_line(15, 0x01)


def test_single_pixel_24mm_bottom_row():
    img = _white_image(128)
    img.putpixel((0, 127), 0)  # black at bottom row
    lines = image_to_pin_lines(img, TAPE_24MM)
    assert len(lines) == 1
    assert lines[0] == _blank_line(0, 0x80)


# --- 2. Single-pixel placement, 12mm tape (left_pin=29, print_dots=70) ---
#
# row 0 -> pin 29+70-1=98 -> byte 98//8=12, MSB_FIRST bit 7-(98%8)=7-2=5 -> mask 0x20.
# bottom row (69) -> pin 29 -> byte 29//8=3, MSB_FIRST bit 7-(29%8)=7-5=2 -> mask 0x04.


def test_single_pixel_12mm_top_row():
    img = _white_image(70)
    img.putpixel((0, 0), 0)
    lines = image_to_pin_lines(img, TAPE_12MM)
    assert len(lines) == 1
    assert lines[0] == _blank_line(12, 0x20)


def test_single_pixel_12mm_bottom_row():
    img = _white_image(70)
    img.putpixel((0, 69), 0)
    lines = image_to_pin_lines(img, TAPE_12MM)
    assert len(lines) == 1
    assert lines[0] == _blank_line(3, 0x04)


# --- 3. flip_pins: row 0 now maps to pin left_pin=29 -> byte 3, mask 0x04 ---
# (identical byte/mask to the non-flipped bottom-row case above, by symmetry.)


def test_flip_pins_12mm_top_row():
    img = _white_image(70)
    img.putpixel((0, 0), 0)
    lines = image_to_pin_lines(img, TAPE_12MM, RasterConfig(flip_pins=True))
    assert len(lines) == 1
    assert lines[0] == _blank_line(3, 0x04)


# --- 4. LSB_FIRST: pin 98 -> byte 12, bit 98%8=2 -> mask 0x04 ---


def test_lsb_first_12mm_top_row():
    img = _white_image(70)
    img.putpixel((0, 0), 0)
    lines = image_to_pin_lines(img, TAPE_12MM, RasterConfig(bit_order=BitOrder.LSB_FIRST))
    assert len(lines) == 1
    assert lines[0] == _blank_line(12, 0x04)


# --- 5. Blank column: PACKBITS -> b"Z"; RAW -> b"\x47\x10\x00" + 16 zero bytes ---
# LE u16 of 16 = bytes 0x10, 0x00.


def test_encode_line_zero_packbits():
    assert encode_line(ZERO_LINE, Compression.PACKBITS) == b"Z"


def test_encode_line_zero_raw():
    assert encode_line(ZERO_LINE, Compression.RAW) == b"\x47\x10\x00" + b"\x00" * 16


# --- 6. PackBits round-trip: non-trivial 16-byte line (mixed runs + literals) ---


def test_encode_line_packbits_roundtrip():
    line = bytes(
        [
            0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0xFF,
            0xFF, 0x10, 0x20, 0x30, 0x40, 0x50, 0x00, 0x00,
        ]
    )
    assert len(line) == BYTES_PER_LINE
    frame = encode_line(line, Compression.PACKBITS)
    assert frame[0] == 0x47
    payload_len = int.from_bytes(frame[1:3], "little")
    payload = frame[3:]
    assert len(payload) == payload_len
    assert frame == b"\x47" + payload_len.to_bytes(2, "little") + payload
    assert packbits.decode(payload) == line


# --- 7. Worst case: alternating-bit line, frame len <= 3 + 17 (PackBits worst case n+1) ---


def test_encode_line_packbits_worst_case():
    line = bytes([0xAA, 0x55] * 8)
    assert len(line) == BYTES_PER_LINE
    frame = encode_line(line, Compression.PACKBITS)
    assert len(frame) <= 3 + 17
    payload = frame[3:]
    assert packbits.decode(payload) == line


# --- 8. Multi-column order: 3-column image with distinct single pixels ---
#
# 24mm tape (left_pin=0, print_dots=128):
# col0 row0   -> pin 127 -> byte 15, mask 0x01
# col1 row127 -> pin 0   -> byte 0,  mask 0x80
# col2 row64  -> pin left_pin+print_dots-1-64=63 -> byte 63//8=7, bit 7-(63%8)=7-7=0 -> mask 0x01


def test_multi_column_order():
    img = Image.new("1", (3, 128), 1)  # width=3, all white
    img.putpixel((0, 0), 0)
    img.putpixel((1, 127), 0)
    img.putpixel((2, 64), 0)
    lines = image_to_pin_lines(img, TAPE_24MM)
    assert len(lines) == 3
    assert lines[0] == _blank_line(15, 0x01)
    assert lines[1] == _blank_line(0, 0x80)
    assert lines[2] == _blank_line(7, 0x01)


# --- 9. Validation ---


def test_image_to_pin_lines_wrong_height_raises():
    img = _white_image(127)  # tape wants 128
    with pytest.raises(ValueError):
        image_to_pin_lines(img, TAPE_24MM)


def test_image_to_pin_lines_wrong_mode_raises():
    img = Image.new("L", (1, 128), 255)
    with pytest.raises(ValueError):
        image_to_pin_lines(img, TAPE_24MM)


def test_image_to_pin_lines_zero_width_raises():
    img = Image.new("1", (0, 128), 1)
    with pytest.raises(ValueError):
        image_to_pin_lines(img, TAPE_24MM)


def test_encode_line_wrong_length_15_raises():
    with pytest.raises(ValueError):
        encode_line(b"\x00" * 15, Compression.PACKBITS)


def test_encode_line_wrong_length_17_raises():
    with pytest.raises(ValueError):
        encode_line(b"\x00" * 17, Compression.RAW)


# --- 10. Cross-check vs geometry: for every TapeSpec, an all-black image encodes to
# lines whose set-bit count == print_dots and whose set bits lie exactly within
# [left_pin, left_pin+print_dots), honoring default bit order (MSB_FIRST).


def _set_pins(line: bytes) -> set[int]:
    pins = set()
    for byte_index, byte in enumerate(line):
        for bit in range(8):
            if byte & (1 << bit):
                pins.add(byte_index * 8 + (7 - bit))  # MSB_FIRST
    return pins


@pytest.mark.parametrize("tape", all_tapes(), ids=lambda t: f"{t.family.name}-{t.nominal_mm}")
def test_all_black_column_matches_print_area(tape: TapeSpec):
    img = _black_image(tape.print_dots)
    lines = image_to_pin_lines(img, tape)
    assert len(lines) == 1
    set_pins = _set_pins(lines[0])
    assert len(set_pins) == tape.print_dots
    assert set_pins == set(range(tape.left_pin, tape.left_pin + tape.print_dots))


# --- encode_image = encode_line over image_to_pin_lines ---


def test_encode_image_matches_encode_line_over_pin_lines():
    img = _white_image(70)
    img.putpixel((0, 0), 0)
    frames = encode_image(img, TAPE_12MM, Compression.PACKBITS)
    pin_lines = image_to_pin_lines(img, TAPE_12MM)
    expected = [encode_line(pins, Compression.PACKBITS) for pins in pin_lines]
    assert frames == expected
