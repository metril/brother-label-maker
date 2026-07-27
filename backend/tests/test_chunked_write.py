"""Tests for task 2.9's chunked write: driver/transport.py's `Transport.
write(..., chunk_size=...)` and driver/printer.py's `print_images(...,
progress_cb=..., chunk_size=...)`.

Two independent layers, tested independently:
  - transport.py: `chunk_size` splits ONE write() call into N sequential
    underlying writes (default None preserves the exact pre-2.9 single-write
    behavior -- see CaptureTransport's own test_capture_transport_* tests in
    test_transport.py, unchanged).
  - printer.py: print_images ALWAYS writes the job stream in chunk_size-byte
    pieces (default 4096) via its own internal loop -- independent of
    transport.write's own chunk_size feature (print_images never passes
    chunk_size down to transport.write; each piece it hands to transport.write
    is already <= chunk_size) -- and optionally reports progress per piece.
"""

from __future__ import annotations

import pytest
from PIL import Image

from labelmaker.driver.geometry import MediaFamily, find_tape
from labelmaker.driver.job import JobOptions, build_job
from labelmaker.driver.printer import print_images
from labelmaker.driver.strategies import get_strategy
from labelmaker.driver.transport import CaptureTransport, MockPrinterTransport

TAPE_24MM = find_tape(24, MediaFamily.TZE)
assert TAPE_24MM is not None


# =====================================================================
# 1. transport.py: Transport.write(..., chunk_size=...)
# =====================================================================


def test_write_without_chunk_size_is_a_single_write():
    transport = CaptureTransport()
    transport.write(b"x" * 10_000)
    assert transport.writes_list == [b"x" * 10_000]
    assert bytes(transport.written) == b"x" * 10_000


def test_write_with_chunk_size_splits_into_n_pieces():
    transport = CaptureTransport()
    data = bytes(range(256)) * 40  # 10_240 bytes
    transport.write(data, chunk_size=4096)
    assert len(transport.writes_list) == 3  # 4096, 4096, 2048
    assert [len(p) for p in transport.writes_list] == [4096, 4096, 2048]
    assert bytes(transport.written) == data  # reassembled, byte-identical


def test_write_with_chunk_size_larger_than_data_is_a_single_piece():
    transport = CaptureTransport()
    transport.write(b"short", chunk_size=4096)
    assert transport.writes_list == [b"short"]


def test_write_with_chunk_size_exact_multiple_of_data_length():
    transport = CaptureTransport()
    data = b"a" * 8192
    transport.write(data, chunk_size=4096)
    assert len(transport.writes_list) == 2
    assert all(len(p) == 4096 for p in transport.writes_list)


def test_write_zero_chunk_size_raises():
    transport = CaptureTransport()
    with pytest.raises(ValueError):
        transport.write(b"some data", chunk_size=0)


def test_write_negative_chunk_size_raises():
    transport = CaptureTransport()
    with pytest.raises(ValueError):
        transport.write(b"some data", chunk_size=-1)


def test_mock_printer_transport_status_reply_still_keys_off_whole_data_when_chunked():
    # STATUS_REQUEST (3 bytes) is far under any realistic chunk_size, but
    # the "ends with STATUS_REQUEST" check must still fire correctly when a
    # chunk_size IS supplied (it keys off the ORIGINAL data, not a piece).
    transport = MockPrinterTransport()
    from labelmaker.driver.protocol import ESC_INIT, FLUSH, STATUS_REQUEST

    transport.write(FLUSH + ESC_INIT + STATUS_REQUEST, chunk_size=16)
    assert transport.read(32) != b""  # the scripted status reply fired


# =====================================================================
# 2. printer.py: print_images(..., progress_cb=..., chunk_size=...)
# =====================================================================


def _big_images(n_columns: int) -> list[Image.Image]:
    # Wide image -> a large job stream (RAW/uncompressed strategy avoids
    # PackBits collapsing a synthetic pattern down to a tiny payload).
    img = Image.new("1", (n_columns, TAPE_24MM.print_dots), 1)
    for x in range(n_columns):
        img.putpixel((x, x % TAPE_24MM.print_dots), 0)  # scattered black pixels
    return [img]


def test_small_job_writes_a_single_chunk():
    transport = MockPrinterTransport()
    strategy = get_strategy("classic")
    images = [Image.new("1", (2, TAPE_24MM.print_dots), 1)]  # tiny job

    events: list[tuple[int, int]] = []
    print_images(
        images,
        strategy=strategy,
        options=JobOptions(),
        transport=transport,
        progress_cb=lambda sent, total: events.append((sent, total)),
        chunk_size=4096,
    )

    # First write is the status request; the job stream itself is the
    # SECOND write -- and since it's well under 4096 bytes, it's exactly one.
    assert len(transport.writes_list) == 2
    assert len(events) == 1
    sent, total = events[0]
    assert sent == total
    assert total == len(transport.writes_list[1])


def test_large_job_writes_n_chunks_and_reports_monotonic_progress():
    transport = MockPrinterTransport()
    strategy = get_strategy("e310bt")  # RAW compression -> large, predictable stream
    images = _big_images(4000)

    # Compute the expected total stream length up front (same build_job the
    # driver itself will call) so this test doesn't need to guess N.
    expected = build_job(images, TAPE_24MM, get_strategy("e310bt"), JobOptions())
    total_len = len(expected.data)
    assert total_len > 4096 * 2  # sanity: this really is a "large" job

    events: list[tuple[int, int]] = []
    print_images(
        images,
        strategy=strategy,
        options=JobOptions(),
        transport=transport,
        progress_cb=lambda sent, total: events.append((sent, total)),
        chunk_size=4096,
    )

    # writes_list[0] is the status request; the rest are the job stream's chunks.
    job_chunks = transport.writes_list[1:]
    import math

    assert len(job_chunks) == math.ceil(total_len / 4096)
    assert len(job_chunks) > 1  # genuinely multiple chunks, not a fluke single write
    assert sum(len(c) for c in job_chunks) == total_len
    assert b"".join(job_chunks) == expected.data  # reassembled, byte-identical

    # progress: one event per chunk, sent is strictly increasing, final == total.
    assert len(events) == len(job_chunks)
    sent_values = [sent for sent, _total in events]
    assert sent_values == sorted(sent_values)  # monotonic
    assert len(set(sent_values)) == len(sent_values)  # strictly increasing
    assert all(total == total_len for _sent, total in events)
    assert events[-1][0] == total_len


def test_progress_cb_is_optional_and_chunking_still_happens_without_it():
    transport = MockPrinterTransport()
    strategy = get_strategy("e310bt")
    images = _big_images(4000)

    print_images(images, strategy=strategy, options=JobOptions(), transport=transport)
    # No progress_cb given -- must not raise, and chunking (default
    # chunk_size=4096) must still have happened.
    job_chunks = transport.writes_list[1:]
    assert len(job_chunks) > 1


def test_chunk_size_is_configurable():
    transport = MockPrinterTransport()
    strategy = get_strategy("e310bt")
    images = _big_images(4000)

    print_images(
        images, strategy=strategy, options=JobOptions(), transport=transport, chunk_size=1024
    )
    job_chunks = transport.writes_list[1:]
    assert all(len(c) <= 1024 for c in job_chunks)
    assert len(job_chunks) > 1


def test_progress_resets_and_stays_monotonic_across_independent_print_images_calls():
    # progress_cb is called with (sent, total) PER print_images() call, so
    # `sent` resets to 0 at the start of each independent invocation; still
    # must stay monotonic WITHIN each call and end at sent==total each time.
    # (The "at most ~10 broadcasts per job, throttled by percentage" rule
    # from the brief is a WORKER-layer policy on top of this raw per-chunk
    # callback -- see test_api_print_task29.py's
    # test_print_broadcasts_job_progress_events_monotonic_and_final_matches_total
    # -- not a constraint on print_images' own callback, which fires once
    # per raw chunk and can legitimately fire more often for a large
    # enough job.)
    transport = MockPrinterTransport()
    strategy = get_strategy("e310bt")
    images = _big_images(3000)

    all_events: list[list[tuple[int, int]]] = []

    def _cb(sent: int, total: int) -> None:
        all_events[-1].append((sent, total))

    for _ in range(2):
        all_events.append([])
        print_images(
            images, strategy=strategy, options=JobOptions(), transport=transport, progress_cb=_cb
        )

    for events in all_events:
        assert events, "expected at least one progress event"
        sent_values = [s for s, _t in events]
        assert sent_values == sorted(sent_values)
        assert events[-1][0] == events[-1][1]  # final sent == total
