"""32-byte printer status parser and retry-driven status request.

Protocol facts (from HANDOFF.md's real probe data, and Brother's family raster
manual for the PT-E550W/P750W/P710BT -- not in-repo; see HANDOFF.md's
References section for the download link. docs/research/protocol.md is
driver-landscape research, not a source of field-level byte facts):

- Status request command: ESC i S (`STATUS_REQUEST`). `request_status()`
  actually writes `FLUSH + ESC_INIT + STATUS_REQUEST` -- the flush/`ESC @`
  init prefix matches the only sequence ever confirmed against real hardware
  (HANDOFF.md:49-51's probe). `FLUSH`/`ESC_INIT`/`STATUS_REQUEST` live in
  protocol.py; `STATUS_REQUEST` is re-exported here for compatibility with
  existing importers of `labelmaker.driver.status.STATUS_REQUEST`.
- Reply is exactly 32 bytes (`STATUS_LEN`). Header: byte0=0x80 (print-head
  mark), byte1=0x20 (block size 32), byte2=0x42 ('B'). See PrinterStatus for
  the decoded fields, and HANDOFF.md's real reference block for byte offsets.
"""

import time
from dataclasses import dataclass
from enum import Enum

from labelmaker.driver.geometry import MediaFamily
from labelmaker.driver.protocol import ESC_INIT, FLUSH, STATUS_REQUEST
from labelmaker.driver.transport import Transport

E720BT_MODEL_CODE = 0x81
STATUS_LEN = 32

_HEADER_BYTE0 = 0x80
_HEADER_BYTE1 = 0x20
_HEADER_BYTE2 = 0x42


class StatusTimeoutError(Exception):
    """Raised when request_status() exhausts its retries without 32 bytes."""


class MediaType(Enum):
    NO_MEDIA = 0x00
    LAMINATED = 0x01
    NON_LAMINATED = 0x03
    HEAT_SHRINK_2_1 = 0x11
    HEAT_SHRINK_3_1 = 0x17
    INCOMPATIBLE = 0xFF


class StatusType(Enum):
    REPLY_TO_REQUEST = 0x00
    PRINTING_COMPLETED = 0x01
    ERROR_OCCURRED = 0x02
    NOTIFICATION = 0x05
    PHASE_CHANGE = 0x06


# Family raster manual (E550W/P750W/P710BT); per-bit meanings not re-verified on E720BT.
_ERROR_INFO1_BITS: dict[int, str] = {
    0x01: "No media",
    0x02: "End of media",
    0x04: "Cutter jam",
    0x08: "Weak batteries",
    0x10: "Printer in use",
}
_ERROR_INFO2_BITS: dict[int, str] = {
    0x01: "Replace media",
    0x04: "Communication error",
    0x10: "Cover open",
    0x20: "Overheating",
}


def _decode_error_bits(value: int, bits: dict[int, str], field_name: str) -> list[str]:
    messages = []
    for bit_index in range(8):
        mask = 1 << bit_index
        if not value & mask:
            continue
        messages.append(bits.get(mask, f"unknown error bit {bit_index} in {field_name}"))
    return messages


@dataclass(frozen=True)
class PrinterStatus:
    raw: bytes
    model_code: int
    series_code: int
    country_code: int
    error_info1: int
    error_info2: int
    media_width_mm: int
    media_type_raw: int
    media_type: MediaType | None
    number_of_colors: int
    status_type_raw: int
    status_type: StatusType | None
    phase_type: int
    phase_number: int
    tape_color_raw: int
    text_color_raw: int

    @property
    def has_error(self) -> bool:
        return bool(self.error_info1 or self.error_info2)

    @property
    def errors(self) -> list[str]:
        return _decode_error_bits(
            self.error_info1, _ERROR_INFO1_BITS, "error_info1"
        ) + _decode_error_bits(self.error_info2, _ERROR_INFO2_BITS, "error_info2")

    @property
    def is_e720bt(self) -> bool:
        return self.model_code == E720BT_MODEL_CODE


def parse_status(data: bytes) -> PrinterStatus:
    """Parse a 32-byte status reply. Raises ValueError on wrong length or bad header."""
    if len(data) != STATUS_LEN:
        raise ValueError(f"status block must be {STATUS_LEN} bytes, got {len(data)}")
    if data[0] != _HEADER_BYTE0:
        raise ValueError(
            f"bad status header byte0: expected 0x{_HEADER_BYTE0:02x}, got 0x{data[0]:02x}"
        )
    if data[1] != _HEADER_BYTE1:
        raise ValueError(
            f"bad status header byte1: expected 0x{_HEADER_BYTE1:02x}, got 0x{data[1]:02x}"
        )
    if data[2] != _HEADER_BYTE2:
        raise ValueError(
            f"bad status header byte2: expected 0x{_HEADER_BYTE2:02x}, got 0x{data[2]:02x}"
        )

    media_type_raw = data[11]
    try:
        media_type = MediaType(media_type_raw)
    except ValueError:
        media_type = None

    status_type_raw = data[18]
    try:
        status_type = StatusType(status_type_raw)
    except ValueError:
        status_type = None

    return PrinterStatus(
        raw=bytes(data),
        series_code=data[3],
        model_code=data[4],
        country_code=data[5],
        error_info1=data[8],
        error_info2=data[9],
        media_width_mm=data[10],
        media_type_raw=media_type_raw,
        media_type=media_type,
        number_of_colors=data[12],
        status_type_raw=status_type_raw,
        status_type=status_type,
        phase_type=data[19],
        # UNVERIFIED: phase_number endianness (LE assumed) — confirm at physical checkpoint.
        # Multi-byte fields in this protocol family are little-endian (e.g. the
        # ESC i d feed amount, the ESC i z raster line count -- see HANDOFF.md);
        # the reference block's phase_number is 0x0000, so endianness here is
        # inferred by family convention, not independently confirmed.
        phase_number=int.from_bytes(data[20:22], "little"),
        tape_color_raw=data[24],
        text_color_raw=data[25],
    )


def media_family_for(media_type: MediaType | None) -> MediaFamily | None:
    """Bridge a decoded status-block MediaType to the geometry.py MediaFamily
    used to look up TapeSpec rows (I4). LAMINATED/NON_LAMINATED are both TZe
    tape; the two heat-shrink media types map to their own families.
    NO_MEDIA, INCOMPATIBLE, and undecoded/unknown (None) media types have no
    corresponding geometry family -- callers fall back to a default (see
    cli.py's `_run_usb_print`).
    """
    if media_type in (MediaType.LAMINATED, MediaType.NON_LAMINATED):
        return MediaFamily.TZE
    if media_type is MediaType.HEAT_SHRINK_2_1:
        return MediaFamily.HSE_2_1
    if media_type is MediaType.HEAT_SHRINK_3_1:
        return MediaFamily.HSE_3_1
    return None


def request_status(
    transport: Transport, *, retries: int = 10, interval_s: float = 0.1
) -> PrinterStatus:
    """Request and parse a status block.

    Writes `FLUSH + ESC_INIT + STATUS_REQUEST` exactly once (C2 -- matches
    the only status-request sequence ever confirmed on real hardware,
    HANDOFF.md:49-51), then polls transport.read(32) up to `retries` times,
    accumulating partial reads until 32 bytes are collected. Sleeps
    `interval_s` after each empty read. Raises StatusTimeoutError if
    `retries` is exhausted before 32 bytes arrive.
    """
    transport.write(FLUSH + ESC_INIT + STATUS_REQUEST)

    buf = bytearray()
    for _ in range(retries):
        chunk = transport.read(STATUS_LEN)
        if chunk:
            buf.extend(chunk)
            if len(buf) >= STATUS_LEN:
                break
        elif interval_s:
            time.sleep(interval_s)

    if len(buf) < STATUS_LEN:
        raise StatusTimeoutError(
            f"status request timed out after {retries} retries; "
            f"collected {len(buf)}/{STATUS_LEN} bytes"
        )
    return parse_status(bytes(buf[:STATUS_LEN]))
