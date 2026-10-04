"""Raster line encoder: 1-bit label bitmap -> per-column raster line frames.

Everything ever printed flows through this module. Protocol facts:

- The printer prints column by column as tape advances: image column x -> raster
  line x. A raster line covers all 128 head pins = 16 bytes.
- The tape's print area occupies pins [tape.left_pin, tape.left_pin + tape.print_dots)
  within the 128-pin line; pins outside the print area are always 0.
- Bit semantics: bit 1 = print (black). PIL mode "1": pixel value 0 = black, so
  pixel 0 -> bit 1.
- Framing (two compression modes), each line is 0x47 ('G') + little-endian u16
  payload length + payload:
    - PACKBITS (RLE mode, `M 0x02`, set elsewhere): payload is the PackBits
      encoding of the 16-byte line. An all-zero line is instead sent as the
      single byte 0x5A ('Z').
    - RAW (no RLE): payload is the 16 raw bytes verbatim. No 'Z' shorthand --
      it is only defined when RLE mode is enabled.
"""

from dataclasses import dataclass
from enum import StrEnum

import packbits
from PIL import Image

from labelmaker.driver.geometry import TapeSpec

BYTES_PER_LINE = 16
ZERO_LINE = b"\x00" * BYTES_PER_LINE

# Byte -> bit-reversed byte, for LSB_FIRST packing (see image_to_pin_lines).
_REVERSE_BITS = bytes(int(f"{b:08b}"[::-1], 2) for b in range(256))

_FRAME_MARKER = 0x47  # 'G'
_ZERO_LINE_MARKER = b"Z"  # 0x5A, PACKBITS-only shorthand for an all-zero line


class Compression(StrEnum):
    """str-valued so JSON/SQLite round-trips are free (Task 1.3a). Values
    only -- member names are unchanged, and no byte stream ever encodes
    these values (see raster.py's framing docstring above)."""

    PACKBITS = "packbits"
    RAW = "raw"


class BitOrder(StrEnum):
    """str-valued so JSON/SQLite round-trips are free (Task 1.3a). Values
    only -- member names are unchanged."""

    MSB_FIRST = "msb_first"
    LSB_FIRST = "lsb_first"


@dataclass(frozen=True)
class RasterConfig:
    # Resolved 2026-07-28 (first physical print): the PT-E720BT needs
    # flip_pins=True and msb_first. These dataclass defaults are deliberately
    # NOT the printer's values: they stay library-neutral so the hand-derived
    # golden literals in test_raster.py/test_job.py remain valid, and the
    # real defaults live in AppConfig (config.py), which the print worker
    # always passes explicitly.
    bit_order: BitOrder = BitOrder.MSB_FIRST
    flip_pins: bool = False


_DEFAULT_CONFIG = RasterConfig()


def set_pin(line: bytearray, pin: int, bit_order: BitOrder = BitOrder.MSB_FIRST) -> None:
    """Set one head-pin's bit within a 16-byte raster line, honoring
    `bit_order` (byte = pin // 8; MSB_FIRST packs pin 0 into byte0's bit 7,
    counting down; LSB_FIRST packs pin 0 into byte0's bit 0, counting up --
    see RasterConfig's docstring).

    The single shared pin-packing primitive for this module: both
    image_to_pin_lines (image-derived lines, below) and job.py's
    _cut_mark_line (a synthetic, non-image-derived line) go through this,
    so a bit_order fix/change only ever needs to happen in one place (task
    2.1 review's original ask -- _cut_mark_line used to hardcode MSB-first
    packing inline instead of sharing this logic, so it silently ignored a
    non-default RasterConfig.bit_order).
    """
    byte_index = pin // 8
    bit = pin % 8 if bit_order is BitOrder.LSB_FIRST else 7 - pin % 8
    line[byte_index] |= 1 << bit


def image_to_pin_lines(
    img: Image.Image, tape: TapeSpec, config: RasterConfig = _DEFAULT_CONFIG
) -> list[bytes]:
    """Convert a 1-bit label image to one 16-byte pin line per image column."""
    if img.mode != "1":
        raise ValueError(f"image mode must be '1', got {img.mode!r}")
    if img.height != tape.print_dots:
        raise ValueError(f"image height {img.height} must equal tape.print_dots {tape.print_dots}")
    if img.width < 1:
        raise ValueError(f"image width must be >= 1, got {img.width}")

    # Vectorized via PIL (this runs while USB_LOCK is held, so the old
    # per-pixel Python loop was costly): lay each image column out as one row
    # of packed bits (y=0 first; PIL's 1 = white, inverted below so black ->
    # 1), then shift that row into its pin position inside a 128-bit
    # big-endian integer. Output is byte-for-byte identical to setting each
    # black pixel's pin via set_pin() (test_raster.py compares against it).
    n = tape.print_dots
    # flip_pins: pin = left_pin + y; otherwise the y axis is reversed first.
    oriented = img if config.flip_pins else img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    packed = oriented.transpose(Image.Transpose.TRANSPOSE).tobytes()
    row_bytes = (n + 7) // 8
    pad_bits = row_bytes * 8 - n
    ink_mask = (1 << n) - 1
    shift = BYTES_PER_LINE * 8 - tape.left_pin - n
    lsb_first = config.bit_order is BitOrder.LSB_FIRST
    lines: list[bytes] = []
    for x in range(img.width):
        row = int.from_bytes(packed[x * row_bytes : (x + 1) * row_bytes], "big")
        line = (((row >> pad_bits) ^ ink_mask) << shift).to_bytes(BYTES_PER_LINE, "big")
        lines.append(line.translate(_REVERSE_BITS) if lsb_first else line)
    return lines


def encode_line(pins: bytes, compression: Compression) -> bytes:
    """Frame one 16-byte pin line for the wire."""
    if len(pins) != BYTES_PER_LINE:
        raise ValueError(f"pins must be exactly {BYTES_PER_LINE} bytes, got {len(pins)}")

    if compression is Compression.PACKBITS:
        if pins == ZERO_LINE:
            return _ZERO_LINE_MARKER
        payload = packbits.encode(pins)
    elif compression is Compression.RAW:
        payload = bytes(pins)
    else:
        raise ValueError(f"unknown compression: {compression!r}")

    return bytes([_FRAME_MARKER]) + len(payload).to_bytes(2, "little") + payload


def encode_image(
    img: Image.Image,
    tape: TapeSpec,
    compression: Compression,
    config: RasterConfig = _DEFAULT_CONFIG,
) -> list[bytes]:
    """Encode a full label image to wire-ready frames, one per image column."""
    return [encode_line(pins, compression) for pins in image_to_pin_lines(img, tape, config)]
