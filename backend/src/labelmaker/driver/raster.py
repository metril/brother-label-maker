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
    # UNVERIFIED: resolve at physical checkpoint (arrow test print)
    bit_order: BitOrder = BitOrder.MSB_FIRST
    flip_pins: bool = False


_DEFAULT_CONFIG = RasterConfig()


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

    pixels = img.load()
    lines: list[bytes] = []
    for x in range(img.width):
        line = bytearray(BYTES_PER_LINE)
        for y in range(tape.print_dots):
            if pixels[x, y] == 0:  # black
                pin = (
                    tape.left_pin + y
                    if config.flip_pins
                    else tape.left_pin + tape.print_dots - 1 - y
                )
                byte_index = pin // 8
                bit = pin % 8 if config.bit_order is BitOrder.LSB_FIRST else 7 - pin % 8
                line[byte_index] |= 1 << bit
        lines.append(bytes(line))
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
