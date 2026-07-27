"""Tests for labelmaker.driver.transport: USB/mock wire transport abstraction.

PyUsbTransport's actual USB read/write/open paths need real hardware and are
exercised at the physical checkpoint via the CLI, not here (see
task-0.4-brief.md). What IS unit-tested here: CaptureTransport (the test
double / PRINTER_MODE=mock backend) and the lazy-import guarantee that
`labelmaker.driver.transport` never touches `usb.core` at module import time.
"""

import subprocess
import sys

from labelmaker.driver.transport import CaptureTransport

# --- 1. CaptureTransport: write recording ---


def test_capture_transport_records_writes_to_written():
    transport = CaptureTransport()
    transport.write(b"\x1b\x69\x53")
    transport.write(b"more")
    assert transport.written == b"\x1b\x69\x53more"


def test_capture_transport_records_writes_to_writes_list():
    transport = CaptureTransport()
    transport.write(b"\x1b\x69\x53")
    transport.write(b"more")
    assert transport.writes_list == [b"\x1b\x69\x53", b"more"]


# --- 2. CaptureTransport: queued reads FIFO ---


def test_capture_transport_queued_reads_are_fifo():
    transport = CaptureTransport()
    transport.queue_read(b"AAAA")
    transport.queue_read(b"BBBB")
    assert transport.read(4) == b"AAAA"
    assert transport.read(4) == b"BBBB"


def test_capture_transport_empty_queue_returns_empty_bytes():
    transport = CaptureTransport()
    assert transport.read(32) == b""


def test_capture_transport_queue_exhausted_after_fifo_drained():
    transport = CaptureTransport()
    transport.queue_read(b"AAAA")
    assert transport.read(4) == b"AAAA"
    assert transport.read(4) == b""


# --- 3. Lazy import of usb.core ---


def test_importing_transport_module_does_not_import_usb():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import labelmaker.driver.transport; import sys; "
            "assert 'usb' not in sys.modules, sys.modules.keys()",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
