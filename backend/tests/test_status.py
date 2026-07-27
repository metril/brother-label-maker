"""Tests for labelmaker.driver.status: 32-byte status parser + retry polling.

The reference block below is real probe data (see HANDOFF.md), not a
hand-fabricated example. All other blocks in this file are built by mutating
copies of it, never by calling parse_status() and trusting the result.
"""

import pytest

from labelmaker.driver.geometry import MediaFamily, find_tape
from labelmaker.driver.protocol import ESC_INIT, FLUSH, STATUS_REQUEST
from labelmaker.driver.status import (
    E720BT_MODEL_CODE,
    REFERENCE_STATUS_BLOCK,
    STATUS_LEN,
    MediaType,
    StatusTimeoutError,
    StatusType,
    media_family_for,
    parse_status,
    request_status,
)
from labelmaker.driver.transport import CaptureTransport

# C2: request_status() now writes this exact flush/init/request sequence
# (matches HANDOFF.md:49-51's confirmed probe sequence), not STATUS_REQUEST alone.
STATUS_REQUEST_SEQUENCE = FLUSH + ESC_INIT + STATUS_REQUEST

# REFERENCE_STATUS_BLOCK (real probe data, HANDOFF.md: 24mm laminated-family
# tape, no errors, model 0x81) now lives in status.py itself (Task 1.3a) --
# single source, imported above instead of redefined here.


def _status_block(overrides: dict[int, int]) -> bytes:
    """Reference block with specific byte offsets overridden."""
    block = bytearray(REFERENCE_STATUS_BLOCK)
    for offset, value in overrides.items():
        block[offset] = value
    return bytes(block)


# --- 1. Reference block golden parse ---


def test_reference_block_golden_parse():
    status = parse_status(REFERENCE_STATUS_BLOCK)
    assert status.raw == REFERENCE_STATUS_BLOCK
    assert status.series_code == 0x30
    assert status.model_code == 0x81
    assert status.country_code == 0x30
    assert status.error_info1 == 0x00
    assert status.error_info2 == 0x00
    assert status.media_width_mm == 24
    assert status.media_type_raw == 0x14
    assert status.media_type is None
    assert status.number_of_colors == 0x01
    assert status.status_type_raw == 0x00
    assert status.status_type is StatusType.REPLY_TO_REQUEST
    assert status.phase_type == 0x00
    assert status.phase_number == 0
    assert status.tape_color_raw == 0x90
    assert status.text_color_raw == 0x08
    assert status.has_error is False
    assert status.errors == []
    assert status.is_e720bt is True


# --- 2. MediaType round-trip ---


@pytest.mark.parametrize(
    "raw,expected",
    [
        (0x00, MediaType.NO_MEDIA),
        (0x01, MediaType.LAMINATED),
        (0x03, MediaType.NON_LAMINATED),
        (0x11, MediaType.HEAT_SHRINK_2_1),
        (0x17, MediaType.HEAT_SHRINK_3_1),
        (0xFF, MediaType.INCOMPATIBLE),
    ],
)
def test_media_type_known_values_round_trip(raw, expected):
    status = parse_status(_status_block({11: raw}))
    assert status.media_type is expected
    assert status.media_type_raw == raw


@pytest.mark.parametrize("raw", [0x14, 0x99])
def test_media_type_unknown_value_decodes_to_none(raw):
    status = parse_status(_status_block({11: raw}))
    assert status.media_type is None
    assert status.media_type_raw == raw


# --- 3. Error decode ---


def test_error_info1_no_media_and_cutter_jam():
    status = parse_status(_status_block({8: 0x05}))
    assert status.errors == ["No media", "Cutter jam"]
    assert status.has_error is True


def test_error_info2_cover_open():
    status = parse_status(_status_block({9: 0x10}))
    assert status.errors == ["Cover open"]
    assert status.has_error is True


def test_error_info1_unknown_bit_message():
    status = parse_status(_status_block({8: 0x80}))
    assert status.has_error is True
    assert len(status.errors) == 1
    assert "unknown error bit" in status.errors[0]


def test_error_info2_unknown_bit_message():
    status = parse_status(_status_block({9: 0x80}))
    assert status.has_error is True
    assert len(status.errors) == 1
    assert "unknown error bit" in status.errors[0]


def test_no_errors_both_zero():
    status = parse_status(REFERENCE_STATUS_BLOCK)
    assert status.errors == []
    assert status.has_error is False


# --- 4. parse_status rejects malformed input ---


def test_parse_status_rejects_31_bytes():
    with pytest.raises(ValueError):
        parse_status(REFERENCE_STATUS_BLOCK[:-1])


def test_parse_status_rejects_33_bytes():
    with pytest.raises(ValueError):
        parse_status(REFERENCE_STATUS_BLOCK + b"\x00")


def test_parse_status_rejects_bad_byte0():
    with pytest.raises(ValueError, match="0x81"):
        parse_status(_status_block({0: 0x81}))


def test_parse_status_rejects_bad_byte1():
    with pytest.raises(ValueError, match="0x21"):
        parse_status(_status_block({1: 0x21}))


def test_parse_status_rejects_bad_byte2():
    with pytest.raises(ValueError, match="0x43"):
        parse_status(_status_block({2: 0x43}))


# --- 5. request_status via CaptureTransport ---


def test_request_status_immediate_full_reply():
    transport = CaptureTransport()
    transport.queue_read(REFERENCE_STATUS_BLOCK)

    status = request_status(transport, interval_s=0)

    assert status.is_e720bt is True
    assert transport.written == STATUS_REQUEST_SEQUENCE


def test_request_status_two_empty_reads_then_full_reply():
    transport = CaptureTransport()
    transport.queue_read(b"")
    transport.queue_read(b"")
    transport.queue_read(REFERENCE_STATUS_BLOCK)

    status = request_status(transport, interval_s=0)

    assert status.raw == REFERENCE_STATUS_BLOCK


def test_request_status_partial_reads_accumulate():
    transport = CaptureTransport()
    transport.queue_read(REFERENCE_STATUS_BLOCK[:16])
    transport.queue_read(REFERENCE_STATUS_BLOCK[16:])

    status = request_status(transport, interval_s=0)

    assert status.raw == REFERENCE_STATUS_BLOCK


def test_request_status_never_replies_raises_timeout():
    transport = CaptureTransport()  # empty queue -> every read() is b""

    with pytest.raises(StatusTimeoutError):
        request_status(transport, retries=3, interval_s=0)

    assert transport.written == STATUS_REQUEST_SEQUENCE  # request sent exactly once


def test_request_status_split_reply_with_empty_read_between():
    transport = CaptureTransport()
    transport.queue_read(REFERENCE_STATUS_BLOCK[:20])
    transport.queue_read(b"")
    transport.queue_read(REFERENCE_STATUS_BLOCK[20:])

    status = request_status(transport, interval_s=0)

    assert status.raw == REFERENCE_STATUS_BLOCK


# --- 6. StatusType decode ---


@pytest.mark.parametrize(
    "raw,expected",
    [
        (0x00, StatusType.REPLY_TO_REQUEST),
        (0x01, StatusType.PRINTING_COMPLETED),
        (0x02, StatusType.ERROR_OCCURRED),
        (0x05, StatusType.NOTIFICATION),
        (0x06, StatusType.PHASE_CHANGE),
    ],
)
def test_status_type_known_values_round_trip(raw, expected):
    status = parse_status(_status_block({18: raw}))
    assert status.status_type is expected
    assert status.status_type_raw == raw


def test_status_type_unknown_raw_decodes_to_none():
    status = parse_status(_status_block({18: 0x99}))
    assert status.status_type is None
    assert status.status_type_raw == 0x99


def test_e720bt_model_code_constant():
    assert E720BT_MODEL_CODE == 0x81


def test_reference_status_block_is_status_len_bytes():
    # Task 1.3a fix round: this was a module-scope `assert` in status.py
    # (stripped under python -O) -- moved here as a real test instead.
    assert len(REFERENCE_STATUS_BLOCK) == STATUS_LEN


# --- 7. media_family_for (I4) ---


def test_media_family_for_laminated_and_non_laminated_map_to_tze():
    assert media_family_for(MediaType.LAMINATED) is MediaFamily.TZE
    assert media_family_for(MediaType.NON_LAMINATED) is MediaFamily.TZE


def test_media_family_for_heat_shrink_families():
    assert media_family_for(MediaType.HEAT_SHRINK_2_1) is MediaFamily.HSE_2_1
    assert media_family_for(MediaType.HEAT_SHRINK_3_1) is MediaFamily.HSE_3_1


def test_media_family_for_no_media_incompatible_and_none_map_to_none():
    assert media_family_for(MediaType.NO_MEDIA) is None
    assert media_family_for(MediaType.INCOMPATIBLE) is None
    assert media_family_for(None) is None


def test_media_family_for_heat_shrink_2_1_resolves_hse_not_tze_spec():
    # media_type 0x11 (HEAT_SHRINK_2_1), status width 9 -> the HSe 8.8mm spec
    # (print_dots=48), not the TZe 9mm spec (print_dots=50) that the same
    # width byte would resolve to under the default TZE family.
    family = media_family_for(MediaType.HEAT_SHRINK_2_1)
    tape = find_tape(9, family)
    assert tape is not None
    assert tape.nominal_mm == 8.8
    assert tape.family is MediaFamily.HSE_2_1
    assert tape.print_dots == 48


# --- 8. to_dict (Task 1.3b: JSON-safe status for the API layer) ---


def test_to_dict_enums_as_values_errors_and_raw_hex_round_trips():
    # Undecoded media_type_raw (0x14, the reference block's real value) ->
    # media_type is None on the dataclass; to_dict must carry that through as
    # JSON null, not crash calling .value on None.
    status = parse_status(REFERENCE_STATUS_BLOCK)
    d = status.to_dict()

    assert d["media_type"] is None
    assert d["media_type_raw"] == 0x14
    assert d["status_type"] == StatusType.REPLY_TO_REQUEST.value
    assert d["has_error"] is False
    assert d["errors"] == []
    assert d["is_e720bt"] is True
    assert d["media_width_mm"] == 24

    raw_roundtrip = bytes.fromhex(d["raw_hex"])
    assert len(raw_roundtrip) == 32
    assert raw_roundtrip == status.raw
    assert " " in d["raw_hex"]  # space-separated, not one long hex blob

    # A block with a decodable media_type and an error set: enums resolve to
    # their plain .value (JSON-safe), not the Enum member itself.
    error_status = parse_status(_status_block({8: 0x01, 11: MediaType.LAMINATED.value}))
    d2 = error_status.to_dict()
    assert d2["media_type"] == MediaType.LAMINATED.value
    assert d2["has_error"] is True
    assert d2["errors"] == ["No media"]
