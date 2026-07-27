"""Tests for labelmaker.driver.transport: USB/mock wire transport abstraction.

PyUsbTransport's `.open()` classmethod (real pyusb device lookup/enumeration)
needs real hardware to succeed end-to-end, and that success path is exercised
at the physical checkpoint via the CLI, not here (see HANDOFF.md and
docs/protocol-notes.md's checkpoint procedure). What IS unit-tested here:
CaptureTransport (the test double / PRINTER_MODE=mock backend); the
lazy-import guarantee that `labelmaker.driver.transport` never touches
`usb.core` at module import time; `.open()`'s error-wrapping (C1: a real
`usb.core.find` monkeypatched to raise USBError/NoBackendError, verifying it
comes out as PrinterNotFoundError); and PyUsbTransport's read/write/close/
kernel-driver logic via a duck-typed fake device injected through the
`PyUsbTransport(device=..., detach=...)` constructor -- a documented test
seam (see PyUsbTransport's docstring) that never requires a real pyusb object.
"""

import subprocess
import sys
import threading

import pytest

from labelmaker.driver import transport as transport_module
from labelmaker.driver.transport import (
    USB_LOCK,
    CaptureTransport,
    PrinterNotFoundError,
    PyUsbTransport,
    TransportError,
)

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


# --- 3b. PyUsbTransport.open(): USB errors wrapped as PrinterNotFoundError (C1) ---
#
# usb.core is genuinely importable in this test environment (pyusb is a
# dependency; only a working *backend* needs real hardware), so these tests
# monkeypatch usb.core.find itself to raise before any backend call happens.


def test_open_wraps_usb_error_as_printer_not_found_error(monkeypatch):
    import usb.core

    def _raise_find(**kwargs):
        raise usb.core.USBError("[Errno 13] Access denied")

    monkeypatch.setattr(usb.core, "find", _raise_find)

    with pytest.raises(PrinterNotFoundError, match="udev permissions"):
        PyUsbTransport.open()


def test_open_wraps_no_backend_error_as_printer_not_found_error(monkeypatch):
    import usb.core

    def _raise_find(**kwargs):
        raise usb.core.NoBackendError("no backend available")

    monkeypatch.setattr(usb.core, "find", _raise_find)

    with pytest.raises(PrinterNotFoundError, match="udev permissions"):
        PyUsbTransport.open()


# --- 4. PyUsbTransport via a duck-typed fake device (I3 test seam) ---
#
# PyUsbTransport(device=fake, detach=...) bypasses `.open()`'s real pyusb
# lookup/interface-claim entirely: production code only reaches this
# constructor through `.open()`, but tests call it directly with a minimal
# fake device object that isn't a pyusb object at all. Error-path tests
# monkeypatch transport._usb_errors() to a pair of stub exception classes
# instead of relying on real usb.core exceptions.


class _StubUSBError(Exception):
    pass


class _StubUSBTimeoutError(_StubUSBError):
    pass


def _stub_usb_errors() -> tuple[type[Exception], type[Exception]]:
    return _StubUSBError, _StubUSBTimeoutError


class _FakeUsbDevice:
    """Minimal duck-typed stand-in for a pyusb Device -- records every call
    made on it, no pyusb object anywhere.
    """

    def __init__(self, kernel_driver_active: bool = False) -> None:
        self.kernel_driver_active = kernel_driver_active
        self.detach_calls: list[int] = []
        self.attach_calls: list[int] = []
        self.attach_raises: Exception | None = None
        self.write_calls: list[tuple[int, bytes, int | None]] = []
        self.write_raises: Exception | None = None
        self.read_calls: list[tuple[int, int, int | None]] = []
        self.read_raises: Exception | None = None
        self.read_result: bytes = b""

    def is_kernel_driver_active(self, interface: int) -> bool:
        return self.kernel_driver_active

    def detach_kernel_driver(self, interface: int) -> None:
        self.detach_calls.append(interface)

    def attach_kernel_driver(self, interface: int) -> None:
        self.attach_calls.append(interface)
        if self.attach_raises is not None:
            raise self.attach_raises

    def write(self, endpoint: int, data: bytes, timeout: int | None = None) -> None:
        self.write_calls.append((endpoint, bytes(data), timeout))
        if self.write_raises is not None:
            raise self.write_raises

    def read(self, endpoint: int, size: int, timeout: int | None = None) -> bytes:
        self.read_calls.append((endpoint, size, timeout))
        if self.read_raises is not None:
            raise self.read_raises
        return self.read_result


# --- 4a. Kernel-driver detach dance (constructor-level, no usb import at all) ---


def test_fake_device_detach_called_when_kernel_driver_active():
    fake = _FakeUsbDevice(kernel_driver_active=True)
    transport = PyUsbTransport(fake, detach=True)
    assert fake.detach_calls == [0]
    assert transport._reattach_kernel_driver is True


def test_fake_device_detach_skipped_when_kernel_driver_not_active():
    fake = _FakeUsbDevice(kernel_driver_active=False)
    transport = PyUsbTransport(fake, detach=True)
    assert fake.detach_calls == []
    assert transport._reattach_kernel_driver is False


def test_fake_device_detach_not_attempted_when_detach_false():
    fake = _FakeUsbDevice(kernel_driver_active=True)
    transport = PyUsbTransport(fake, detach=False)
    assert fake.detach_calls == []
    assert transport._reattach_kernel_driver is False


# --- 4b. read(): timeout -> b"", other USBError -> TransportError ---


def test_fake_device_read_timeout_returns_empty_bytes(monkeypatch):
    monkeypatch.setattr(transport_module, "_usb_errors", _stub_usb_errors)
    fake = _FakeUsbDevice()
    fake.read_raises = _StubUSBTimeoutError("timed out")
    transport = PyUsbTransport(fake)

    assert transport.read(32) == b""


def test_fake_device_read_other_usb_error_raises_transport_error(monkeypatch):
    monkeypatch.setattr(transport_module, "_usb_errors", _stub_usb_errors)
    fake = _FakeUsbDevice()
    fake.read_raises = _StubUSBError("access denied")
    transport = PyUsbTransport(fake)

    with pytest.raises(TransportError, match="access denied"):
        transport.read(32)


def test_fake_device_read_success_returns_bytes():
    fake = _FakeUsbDevice()
    fake.read_result = b"\x80\x20\x42"
    transport = PyUsbTransport(fake)

    assert transport.read(3, timeout_ms=750) == b"\x80\x20\x42"
    assert fake.read_calls == [(PyUsbTransport.EP_IN, 3, 750)]


# --- 4c. write(): passes timeout through; other USBError -> TransportError ---


def test_fake_device_write_passes_timeout_to_device():
    fake = _FakeUsbDevice()
    transport = PyUsbTransport(fake)

    transport.write(b"\x01\x02", timeout_ms=5000)

    assert fake.write_calls == [(PyUsbTransport.EP_OUT, b"\x01\x02", 5000)]


def test_fake_device_write_other_usb_error_raises_transport_error(monkeypatch):
    monkeypatch.setattr(transport_module, "_usb_errors", _stub_usb_errors)
    fake = _FakeUsbDevice()
    fake.write_raises = _StubUSBError("write failed")
    transport = PyUsbTransport(fake)

    with pytest.raises(TransportError, match="write failed"):
        transport.write(b"\x01")


# --- 4d. close(): releases + best-effort reattaches, swallowing errors ---


def test_fake_device_close_releases_interface_and_reattaches(monkeypatch):
    import usb.util

    release_calls = []
    monkeypatch.setattr(
        usb.util,
        "release_interface",
        lambda device, interface: release_calls.append((device, interface)),
    )
    monkeypatch.setattr(transport_module, "_usb_errors", _stub_usb_errors)

    fake = _FakeUsbDevice(kernel_driver_active=True)
    transport = PyUsbTransport(fake, detach=True)

    transport.close()

    assert release_calls == [(fake, 0)]
    assert fake.attach_calls == [0]


def test_fake_device_close_swallows_release_errors(monkeypatch):
    import usb.util

    def _raise_release(device, interface):
        raise _StubUSBError("release failed")

    monkeypatch.setattr(usb.util, "release_interface", _raise_release)
    monkeypatch.setattr(transport_module, "_usb_errors", _stub_usb_errors)

    fake = _FakeUsbDevice(kernel_driver_active=False)
    transport = PyUsbTransport(fake, detach=True)

    transport.close()  # must not raise


def test_fake_device_close_swallows_reattach_errors(monkeypatch):
    import usb.util

    monkeypatch.setattr(usb.util, "release_interface", lambda device, interface: None)
    monkeypatch.setattr(transport_module, "_usb_errors", _stub_usb_errors)

    fake = _FakeUsbDevice(kernel_driver_active=True)
    fake.attach_raises = _StubUSBError("reattach failed")
    transport = PyUsbTransport(fake, detach=True)

    transport.close()  # must not raise

    assert fake.attach_calls == [0]


# --- 5. USB_LOCK: the process-wide lock primitive itself (C1) ---
#
# USB_LOCK is a module-level singleton shared by the WHOLE test session (not
# just this file) -- jobs/worker.py and api/router_printer.py both take it
# in production code, and other tests (test_usb_lock.py) exercise it through
# those call sites. Every test here is careful to release anything it
# acquires, even on assertion failure, so it can never leave the lock held
# and deadlock an unrelated later test.


def test_usb_lock_is_a_real_lock_free_by_default():
    # A fresh acquire must succeed immediately -- nothing else in the test
    # session should be holding it at rest.
    acquired = USB_LOCK.acquire(timeout=1)
    try:
        assert acquired is True
    finally:
        if acquired:
            USB_LOCK.release()


def test_usb_lock_timeout_acquire_fails_while_held_then_succeeds_after_release():
    held = threading.Event()
    release = threading.Event()

    def _holder() -> None:
        USB_LOCK.acquire()
        held.set()
        release.wait(timeout=5)
        USB_LOCK.release()

    holder_thread = threading.Thread(target=_holder)
    holder_thread.start()
    try:
        assert held.wait(timeout=2), "holder thread never acquired USB_LOCK"
        # Short timeout, held lock -> must return False promptly, not block.
        assert USB_LOCK.acquire(timeout=0.2) is False
    finally:
        release.set()
        holder_thread.join(timeout=2)
        assert not holder_thread.is_alive()

    # Released now -- a fresh acquire must succeed.
    acquired = USB_LOCK.acquire(timeout=1)
    try:
        assert acquired is True
    finally:
        if acquired:
            USB_LOCK.release()
