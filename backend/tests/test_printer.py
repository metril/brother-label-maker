"""Tests for labelmaker.driver.printer: the high-level print_images() API
extracted from cli._run_usb_print, plus the MockPrinterTransport double it
(and the future web app) exercise it against.

No real USB anywhere: every test here uses MockPrinterTransport
(transport.py), which answers every status request from a scripted 32-byte
block (REFERENCE_STATUS_BLOCK by default -- the same Task-0.4 real probe
data test_status.py/test_cli.py use) and returns b"" for anything else, so
request_status() never times out and post-print drains never stall.
"""

import json
import subprocess
import sys

import pytest
from PIL import Image

from labelmaker.driver.geometry import MediaFamily, find_tape
from labelmaker.driver.job import ChainMode, JobOptions, build_job
from labelmaker.driver.printer import (
    PrinterBusyError,
    PrintResult,
    TapeNotFoundError,
    get_status,
    print_images,
)
from labelmaker.driver.protocol import ESC_INIT, FLUSH, STATUS_REQUEST
from labelmaker.driver.raster import BitOrder, Compression
from labelmaker.driver.status import (
    REFERENCE_STATUS_BLOCK,
    PrinterStatus,
    StatusType,
    request_status,
)
from labelmaker.driver.strategies import ClassicStrategy, E310BTStrategy, get_strategy
from labelmaker.driver.transport import MockPrinterTransport, TransportError

STATUS_REQUEST_SEQUENCE = FLUSH + ESC_INIT + STATUS_REQUEST

TAPE_24MM = find_tape(24, MediaFamily.TZE)  # print_dots=128
assert TAPE_24MM is not None


def _status_block(overrides: dict[int, int]) -> bytes:
    """REFERENCE_STATUS_BLOCK with specific byte offsets overridden."""
    block = bytearray(REFERENCE_STATUS_BLOCK)
    for offset, value in overrides.items():
        block[offset] = value
    return bytes(block)


def _image(print_dots: int, width: int = 3) -> list[Image.Image]:
    return [Image.new("1", (width, print_dots), 1)]


class _RaisingAfterQueueTransport(MockPrinterTransport):
    """MockPrinterTransport whose read() raises TransportError once its
    queued replies (and the automatic status reply) are exhausted, instead
    of returning b"" -- simulates a transport failure during the post-print
    drain (Task 1.3a fix round: printer._drain_post_print's TransportError
    branch)."""

    def read(self, n: int, timeout_ms: int = 500) -> bytes:
        if self._read_queue:
            return self._read_queue.pop(0)
        if self._pending_status_reply:
            self._pending_status_reply = False
            return self._status_reply
        raise TransportError("USB read error: [Errno 5] Input/output error")


# =====================================================================
# 1. print_images happy path (composition check against build_job)
# =====================================================================


def test_print_images_happy_path_matches_build_job_and_resolves_24mm_tze():
    transport = MockPrinterTransport()
    strategy = get_strategy("classic")
    options = JobOptions()
    images = _image(TAPE_24MM.print_dots)

    result = print_images(images, strategy=strategy, options=options, transport=transport)

    assert isinstance(result, PrintResult)
    # build_job itself is golden-locked (test_job.py) -- this is a pure
    # composition check that print_images calls it with the same inputs and
    # writes exactly its output, not a re-derivation of the byte stream.
    expected = build_job(images, TAPE_24MM, get_strategy("classic"), options)
    assert bytes(transport.written) == STATUS_REQUEST_SEQUENCE + expected.data
    assert result.job.data == expected.data
    assert result.status_before.raw == REFERENCE_STATUS_BLOCK
    assert result.tape == TAPE_24MM
    assert result.assumed_tze is True  # REFERENCE_STATUS_BLOCK's media_type_raw 0x14 is undecoded


def test_print_images_accepts_prefetched_status_and_skips_internal_request():
    # The CLI must resolve tape.print_dots (to size its test-pattern images)
    # from the SAME status it later hands to print_images -- passing
    # status_before must not issue a second status request over the wire
    # (the checkpoint CLI's golden tests only ever queue one reply).
    transport = MockPrinterTransport()
    status = request_status(transport, interval_s=0)
    strategy = get_strategy("classic")
    images = _image(TAPE_24MM.print_dots)

    result = print_images(
        images,
        strategy=strategy,
        options=JobOptions(),
        transport=transport,
        status_before=status,
    )

    assert bytes(transport.written) == STATUS_REQUEST_SEQUENCE + result.job.data
    assert result.status_before is status


# =====================================================================
# 2. Busy printer -> PrinterBusyError, nothing written after the status request
# =====================================================================


def test_print_images_raises_printer_busy_error_and_writes_nothing_else():
    transport = MockPrinterTransport(status_reply=_status_block({8: 0x01}))  # No media
    strategy = get_strategy("classic")
    images = _image(TAPE_24MM.print_dots)

    with pytest.raises(PrinterBusyError):
        print_images(images, strategy=strategy, options=JobOptions(), transport=transport)

    assert bytes(transport.written) == STATUS_REQUEST_SEQUENCE


# =====================================================================
# 3. Tape resolution: HSe known media type vs. unknown/undecoded media type
# =====================================================================


def test_print_images_hse_media_type_resolves_hse_8_8mm_not_assumed():
    block = _status_block({10: 9, 11: 0x11})  # HEAT_SHRINK_2_1, status width 9 -> HSe 8.8mm
    transport = MockPrinterTransport(status_reply=block)
    strategy = get_strategy("classic")
    tape = find_tape(9, MediaFamily.HSE_2_1)
    assert tape is not None
    images = _image(tape.print_dots)

    result = print_images(images, strategy=strategy, options=JobOptions(), transport=transport)

    assert result.tape == tape
    assert result.tape.nominal_mm == 8.8
    assert result.assumed_tze is False


def test_print_images_unknown_media_type_assumes_tze():
    transport = MockPrinterTransport()  # media_type_raw 0x14, still undecoded
    strategy = get_strategy("classic")
    images = _image(TAPE_24MM.print_dots)

    result = print_images(images, strategy=strategy, options=JobOptions(), transport=transport)

    assert result.assumed_tze is True
    assert result.tape == TAPE_24MM


def test_print_images_no_tape_spec_raises_tape_not_found_error():
    block = _status_block({10: 99})  # no TapeSpec has status_width_mm == 99
    transport = MockPrinterTransport(status_reply=block)
    strategy = get_strategy("classic")

    with pytest.raises(TapeNotFoundError):
        print_images(
            [Image.new("1", (2, 10), 1)],
            strategy=strategy,
            options=JobOptions(),
            transport=transport,
        )


# =====================================================================
# 4. Post-print drain: early break on ERROR_OCCURRED, only blocks up to it consumed
# =====================================================================


def test_print_images_drain_stops_at_error_occurred_block():
    transport = MockPrinterTransport()
    # Pre-print status first (consumes the automatic REFERENCE_STATUS_BLOCK
    # reply while the queue is still empty), THEN queue the post-print
    # drain's scripted replies -- queued reads take priority over the
    # automatic status reply (see MockPrinterTransport docstring), so
    # queuing before the pre-print fetch would feed the wrong block there.
    status = request_status(transport, interval_s=0)
    error_block = _status_block({18: StatusType.ERROR_OCCURRED.value, 8: 0x01})  # No media
    transport.queue_read(error_block)
    transport.queue_read(REFERENCE_STATUS_BLOCK)  # must NOT be consumed (early break)
    strategy = get_strategy("classic")
    images = _image(TAPE_24MM.print_dots)

    result = print_images(
        images, strategy=strategy, options=JobOptions(), transport=transport, status_before=status
    )

    assert len(result.post_print_events) == 1
    assert isinstance(result.post_print_events[0], PrinterStatus)
    assert result.post_print_events[0].status_type is StatusType.ERROR_OCCURRED
    assert result.post_print_events[0].errors == ["No media"]
    assert result.blocks_seen == 1


def test_print_images_no_post_print_status_returns_empty_list():
    transport = MockPrinterTransport()  # nothing queued -> drain reads all return b""
    strategy = get_strategy("classic")
    images = _image(TAPE_24MM.print_dots)

    result = print_images(images, strategy=strategy, options=JobOptions(), transport=transport)

    assert result.post_print_events == []
    assert result.blocks_seen == 0


# --- 4b. Drain diagnostics (Task 1.3a fix round): malformed blocks and
# TransportError during the drain must still surface as ordered notes, not
# silently vanish (the pre-refactor behavior this preserves) ---


def test_print_images_drain_malformed_block_only():
    transport = MockPrinterTransport()
    status = request_status(transport, interval_s=0)
    bad_block = _status_block({0: 0x81})  # bad header byte0 -> parse_status raises ValueError
    transport.queue_read(bad_block)
    strategy = get_strategy("classic")
    images = _image(TAPE_24MM.print_dots)

    result = print_images(
        images, strategy=strategy, options=JobOptions(), transport=transport, status_before=status
    )

    assert len(result.post_print_events) == 1
    assert isinstance(result.post_print_events[0], str)
    assert result.post_print_events[0] == (
        "malformed block (bad status header byte0: expected 0x80, got 0x81)"
    )
    assert result.blocks_seen == 1  # the block WAS received, just failed to parse


def test_print_images_drain_malformed_then_completed_preserves_order():
    transport = MockPrinterTransport()
    status = request_status(transport, interval_s=0)
    bad_block = _status_block({0: 0x81})
    completed_block = _status_block({18: StatusType.PRINTING_COMPLETED.value})
    transport.queue_read(bad_block)
    transport.queue_read(completed_block)
    strategy = get_strategy("classic")
    images = _image(TAPE_24MM.print_dots)

    result = print_images(
        images, strategy=strategy, options=JobOptions(), transport=transport, status_before=status
    )

    assert len(result.post_print_events) == 2
    assert isinstance(result.post_print_events[0], str)
    assert "malformed block" in result.post_print_events[0]
    assert isinstance(result.post_print_events[1], PrinterStatus)
    assert result.post_print_events[1].status_type is StatusType.PRINTING_COMPLETED
    assert result.blocks_seen == 2


def test_print_images_drain_transport_error_first_leaves_blocks_seen_zero():
    transport = _RaisingAfterQueueTransport()
    status = request_status(transport, interval_s=0)
    strategy = get_strategy("classic")
    images = _image(TAPE_24MM.print_dots)

    result = print_images(
        images, strategy=strategy, options=JobOptions(), transport=transport, status_before=status
    )

    assert result.post_print_events == [
        "read failed (USB read error: [Errno 5] Input/output error)"
    ]
    # No block was ever received -- CLI's final "no post-print status
    # received" line still gates on this, printing *alongside* the note
    # (matches the pre-refactor CLI's `received_any`-driven quirk exactly).
    assert result.blocks_seen == 0


def test_print_images_drain_status_then_transport_error_preserves_order():
    transport = _RaisingAfterQueueTransport()
    status = request_status(transport, interval_s=0)
    notification_block = _status_block({18: StatusType.NOTIFICATION.value})
    transport.queue_read(notification_block)
    strategy = get_strategy("classic")
    images = _image(TAPE_24MM.print_dots)

    result = print_images(
        images, strategy=strategy, options=JobOptions(), transport=transport, status_before=status
    )

    assert len(result.post_print_events) == 2
    assert isinstance(result.post_print_events[0], PrinterStatus)
    assert result.post_print_events[0].status_type is StatusType.NOTIFICATION
    assert result.post_print_events[1] == (
        "read failed (USB read error: [Errno 5] Input/output error)"
    )
    assert result.blocks_seen == 1  # the notification block WAS received


# =====================================================================
# 5. Transport lifecycle: print_images never closes the transport
# =====================================================================


def test_print_images_does_not_close_transport():
    transport = MockPrinterTransport()
    strategy = get_strategy("classic")
    images = _image(TAPE_24MM.print_dots)

    print_images(images, strategy=strategy, options=JobOptions(), transport=transport)

    assert transport.closed is False


def test_get_status_is_thin_passthrough_to_request_status():
    transport = MockPrinterTransport()
    status = get_status(transport)
    assert status.raw == REFERENCE_STATUS_BLOCK


# =====================================================================
# 6. MockPrinterTransport semantics
# =====================================================================


def test_mock_printer_transport_answers_status_requests_repeatedly():
    transport = MockPrinterTransport()
    for _ in range(3):
        status = request_status(transport, interval_s=0)
        assert status.raw == REFERENCE_STATUS_BLOCK


def test_mock_printer_transport_write_without_status_request_then_read_is_empty():
    transport = MockPrinterTransport()
    transport.write(b"\x1b\x40")  # ESC @ alone -- does not end with STATUS_REQUEST
    assert transport.read(32) == b""


def test_mock_printer_transport_status_reply_consumed_once_per_request():
    transport = MockPrinterTransport()
    transport.write(STATUS_REQUEST_SEQUENCE)
    assert transport.read(32) == REFERENCE_STATUS_BLOCK
    assert transport.read(32) == b""  # second read after the same request -> empty


def test_mock_printer_transport_queued_read_takes_priority_over_status_reply():
    transport = MockPrinterTransport()
    transport.queue_read(b"scripted")
    transport.write(STATUS_REQUEST_SEQUENCE)
    assert transport.read(32) == b"scripted"


def test_mock_printer_transport_custom_status_reply():
    custom = _status_block({10: 12})
    transport = MockPrinterTransport(status_reply=custom)
    status = request_status(transport, interval_s=0)
    assert status.media_width_mm == 12


def test_mock_printer_transport_rejects_wrong_length_status_reply():
    with pytest.raises(ValueError, match="32"):
        MockPrinterTransport(status_reply=b"\x80\x20\x42")


# =====================================================================
# 7. get_strategy
# =====================================================================


def test_get_strategy_returns_named_instances():
    assert isinstance(get_strategy("classic"), ClassicStrategy)
    assert isinstance(get_strategy("e310bt"), E310BTStrategy)


def test_get_strategy_unknown_name_raises_key_error_listing_valid_names():
    with pytest.raises(KeyError) as exc_info:
        get_strategy("bogus")
    message = str(exc_info.value)
    assert "classic" in message
    assert "e310bt" in message


# =====================================================================
# 8. Str-valued enums: value/round-trip/json
# =====================================================================


def test_chain_mode_is_str_valued_and_round_trips():
    assert ChainMode.CUT_EACH.value == "cut_each"
    assert ChainMode("cut_each") is ChainMode.CUT_EACH
    assert ChainMode.CHAIN_FF.value == "chain_ff"
    assert ChainMode("chain_ff") is ChainMode.CHAIN_FF
    assert ChainMode.STRIP_MARKS.value == "strip_marks"
    assert ChainMode("strip_marks") is ChainMode.STRIP_MARKS
    assert json.loads(json.dumps({"mode": ChainMode.CUT_EACH})) == {"mode": "cut_each"}


def test_compression_is_str_valued_and_round_trips():
    assert Compression.PACKBITS.value == "packbits"
    assert Compression("packbits") is Compression.PACKBITS
    assert Compression.RAW.value == "raw"
    assert Compression("raw") is Compression.RAW
    assert json.loads(json.dumps({"c": Compression.PACKBITS})) == {"c": "packbits"}


def test_bit_order_is_str_valued_and_round_trips():
    assert BitOrder.MSB_FIRST.value == "msb_first"
    assert BitOrder("msb_first") is BitOrder.MSB_FIRST
    assert BitOrder.LSB_FIRST.value == "lsb_first"
    assert BitOrder("lsb_first") is BitOrder.LSB_FIRST
    assert json.loads(json.dumps({"b": BitOrder.LSB_FIRST})) == {"b": "lsb_first"}


# =====================================================================
# 9. Layering: strategies.py no longer imports job.py at runtime
# =====================================================================


def test_importing_strategies_does_not_import_job():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import labelmaker.driver.strategies; import sys; "
            "assert 'labelmaker.driver.job' not in sys.modules, sys.modules.keys()",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
