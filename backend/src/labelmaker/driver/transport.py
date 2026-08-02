"""Wire transports for the PT-E720BT: real USB bulk transfer and in-memory
test doubles.

`usb.core` / `usb.util` are imported lazily -- inside methods, never at
module import time -- so that importing this module, using `CaptureTransport`
/`MockPrinterTransport` (the test doubles and the `PRINTER_MODE=mock`
backend), and running the test suite / CI never require libusb to be
installed. `MockPrinterTransport`'s default status reply lazily imports
`labelmaker.driver.status.REFERENCE_STATUS_BLOCK` for the same reason status
already imports `Transport` from this module -- a module-level import here
would be circular.
"""

import threading
from typing import Protocol

from labelmaker.driver.protocol import STATUS_REQUEST

# C1: one process-wide lock shared by EVERY code path that opens the USB
# transport -- jobs/worker.py's print path and api/router_printer.py's
# status path both take it around the transport's full open -> ... -> close
# lifetime (this module deliberately does NOT take it inside
# PyUsbTransport.open() itself -- see that method's docstring -- so the
# caller controls exactly how much of its own work happens under the lock).
# A single real USB device only supports one in-flight conversation at a
# time; without this, a status poll landing mid-print corrupts both.
# Plain threading.Lock (not RLock): every acquire/release pair here is used
# from a single `anyio.to_thread.run_sync`-run synchronous call, never
# re-entered.
USB_LOCK = threading.Lock()


class PrinterNotFoundError(Exception):
    """Raised when PyUsbTransport.open() finds no matching USB device, or when
    opening the device fails outright (a wrapped usb.core.USBError/NoBackendError).
    """


class TransportError(Exception):
    """Raised when a USB read or write fails for a reason other than a timeout
    (timeouts are not errors -- read() returns b"" instead, per the Transport
    protocol).
    """


def _split_into_chunks(data: bytes, chunk_size: int | None) -> list[bytes]:
    """Task 2.9's chunked-write helper: split `data` into pieces of at most
    `chunk_size` bytes each, in order, covering every byte exactly once.
    `chunk_size=None` (the default everywhere `write()` is called without it
    -- every pre-2.9 call site) is a no-op: returns `[data]` unchanged, so
    every existing Transport implementation/test keeps its exact prior
    single-write behavior. An empty `data` always yields `[data]` (one
    "chunk", possibly empty) rather than `[]`, so a caller that always does
    at least one write per `write()` call keeps doing so.
    """
    if chunk_size is None or not data:
        return [data]
    if chunk_size <= 0:
        raise ValueError(f"chunk_size must be positive, got {chunk_size}")
    return [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]


class Transport(Protocol):
    def write(self, data: bytes, timeout_ms: int = 10000, chunk_size: int | None = None) -> None:
        """Write `data`. `chunk_size` (task 2.9), when given, splits `data`
        into sequential pieces of at most that many bytes each -- each piece
        is its own underlying write, still within `timeout_ms` per piece --
        instead of one single potentially-huge transfer. `None` (the
        default) preserves the pre-2.9 single-write behavior exactly."""
        ...

    def read(self, n: int, timeout_ms: int = 500) -> bytes:
        """Read up to n bytes. Returns b"" on timeout; may return fewer than n bytes."""
        ...

    def close(self) -> None: ...


class CaptureTransport:
    """Test double and the `PRINTER_MODE=mock` backend transport.

    Records every write; serves scripted replies from a FIFO read queue.
    """

    def __init__(self) -> None:
        self.written = bytearray()
        self.writes_list: list[bytes] = []
        self._read_queue: list[bytes] = []

    def write(self, data: bytes, timeout_ms: int = 10000, chunk_size: int | None = None) -> None:
        # timeout_ms is part of the Transport protocol (I2) but meaningless
        # for an in-memory double -- accepted and ignored. When chunk_size
        # splits `data`, each piece is recorded as its OWN writes_list entry
        # (not the original, unsplit `data`) -- writes_list is meant to
        # mirror what actually went out over "the wire" one piece at a
        # time, which is exactly what a real chunked transport would do.
        for piece in _split_into_chunks(data, chunk_size):
            self.written.extend(piece)
            self.writes_list.append(bytes(piece))

    def queue_read(self, data: bytes) -> None:
        """Queue one scripted reply. Each read() call pops the next one, FIFO."""
        self._read_queue.append(data)

    def read(self, n: int, timeout_ms: int = 500) -> bytes:
        if not self._read_queue:
            return b""
        return self._read_queue.pop(0)

    def close(self) -> None:
        pass


class MockPrinterTransport(CaptureTransport):
    """The `PRINTER_MODE=mock` backend transport: a CaptureTransport that
    additionally behaves like a real printer's status-request cycle, so
    request_status() never times out against it and post-print drains never
    stall.

    Every write() that ends with STATUS_REQUEST (`ESC i S`) arms a one-shot
    reply: the *next* read() returns `status_reply` (32 bytes, the same
    shape as a real status block) instead of the usual CaptureTransport
    empty-queue b"". Any explicitly `queue_read()`-ed reply still takes
    priority (FIFO, CaptureTransport behavior) -- this only fills in when
    the queue is empty, so tests can still script specific replies (e.g. a
    post-print ERROR_OCCURRED block) on top of the automatic status replies.
    """

    def __init__(self, status_reply: bytes | None = None) -> None:
        super().__init__()
        # Lazy import (both the default and the length check need STATUS_LEN
        # too) -- see module docstring for why this can't be a module-level
        # import.
        from labelmaker.driver.status import REFERENCE_STATUS_BLOCK, STATUS_LEN

        if status_reply is None:
            status_reply = REFERENCE_STATUS_BLOCK
        if len(status_reply) != STATUS_LEN:
            raise ValueError(
                f"status_reply must be exactly {STATUS_LEN} bytes, got {len(status_reply)}"
            )
        self._status_reply = status_reply
        self._pending_status_reply = False
        self.closed = False

    def write(self, data: bytes, timeout_ms: int = 10000, chunk_size: int | None = None) -> None:
        super().write(data, timeout_ms, chunk_size)
        # Checked against the ORIGINAL, unsplit `data` -- whether the
        # status-request suffix is present doesn't depend on how many
        # pieces it got recorded as.
        self._pending_status_reply = bytes(data).endswith(STATUS_REQUEST)

    def read(self, n: int, timeout_ms: int = 500) -> bytes:
        if self._read_queue:
            return super().read(n, timeout_ms)
        if self._pending_status_reply:
            self._pending_status_reply = False
            return self._status_reply
        return b""

    def close(self) -> None:
        self.closed = True
        super().close()


def _usb_errors() -> tuple[type[Exception], type[Exception]]:
    """Lazy import of usb.core's exception classes, returned as a pair
    (USBError, USBTimeoutError). A monkeypatch seam: called instead of
    importing usb.core directly inside read()/write()/close(), so tests can
    inject stub exception classes and exercise the error-handling branches
    with a duck-typed fake device -- no real pyusb object, no usb.core
    dependency at test time (see test_transport.py).
    """
    import usb.core

    return usb.core.USBError, usb.core.USBTimeoutError


def _fresh_libusb_backend():
    """Build a brand-new libusb1 context instead of reusing pyusb's
    process-lifetime-cached one -- Track B's fix for the in-container
    hotplug gap (docs/usb-setup.md §Hotplug).

    A bare `usb.core.find(...)` (no `backend=`) falls back to
    `usb.backend.libusb1.get_backend()`, which memoizes its `_LibUSB`
    instance in a module-global (`_lib_object`) for the life of the
    process: one `libusb_init`'d context, reused by every find()/open()
    call forever. That context's device list is populated once (from
    sysfs) and afterwards kept "current" only via libusb's own hotplug
    notifications -- and whether those notifications even reach a
    long-running containerized process is exactly the other half of the
    gap docs/usb-setup.md's "Hotplug / power-cycle behavior" section
    documents (Docker's bridged network namespace may not deliver the
    udev uevent at all). Regardless of that half, a printer
    unplugged/replugged or power-cycled while the container keeps running
    can leave the *cached context's* device list stale, so `usb.core.find`
    returns nothing (or a subsequent open fails with a stale-node ENODEV)
    until something forces a fresh context -- today, only a full container
    restart does that.

    This builds that "fresh context" on every PyUsbTransport.open() call
    instead of waiting for a restart. It reuses `get_backend()`'s cached
    singleton only to grab its already-`dlopen`'d `.lib` handle (loading
    libusb itself is the expensive, one-time part -- fine to keep sharing),
    then constructs a NEW `usb.backend.libusb1._LibUSB(base.lib)`, whose
    `__init__` runs its own `libusb_init` -> a full sysfs re-scan,
    independent of and without touching the module-global cached singleton
    at all. Every open() therefore gets the same fresh device list a
    container restart would have given it, without requiring one. (pyusb
    exposes no public "re-scan this existing context" call -- the only way
    to force a re-enumeration is a brand-new context, which is why this
    builds one rather than trying to refresh the cached singleton in
    place.)

    Returns None if no libusb1 backend is available at all (mirrors
    `get_backend()`'s own None-on-failure contract). Callers pass that
    straight through as `backend=None` to `usb.core.find`, which then runs
    its own normal multi-backend search exactly as it does today when no
    backend is constructed here -- this function never makes the
    no-backend-available case any worse.

    # UNVERIFIED: this closes the *stale-context* half of the documented
    hotplug gap in theory (fresh libusb_init -> fresh sysfs scan on every
    open); confirming it actually picks up a mid-session replug against the
    real PT-E720BT is still pending the physical checkpoint. The *uevent
    delivery* half of the gap (see docstring above) is untouched by this
    change either way.
    """
    import usb.backend.libusb1

    base = usb.backend.libusb1.get_backend()
    if base is None:
        return None
    return usb.backend.libusb1._LibUSB(base.lib)


class PyUsbTransport:
    """Real USB bulk transport. Opened fresh per print job -- callers re-open
    on every job rather than caching a device handle across power cycles; no
    reconnect logic here by design. Since Track B, each open() also builds a
    brand-new libusb1 context (see `_fresh_libusb_backend()`) rather than
    reusing pyusb's process-lifetime-cached one, so a printer replugged
    while the process keeps running doesn't need a container restart to be
    found again -- see that function's docstring and docs/usb-setup.md
    §Hotplug.
    """

    VENDOR_ID = 0x04F9
    PRODUCT_ID = 0x224A
    EP_OUT = 0x02
    EP_IN = 0x81

    def __init__(
        self,
        device,
        ep_out: int = EP_OUT,
        ep_in: int = EP_IN,
        *,
        detach: bool = False,
        backend=None,
    ) -> None:
        """Wrap an already-found device. `open()` is the production entry point
        (real pyusb lookup + interface claim); this constructor is also a
        documented **test seam**: tests call `PyUsbTransport(device=fake,
        detach=...)` directly with a minimal duck-typed fake device object,
        bypassing pyusb/usb.core entirely (see test_transport.py).

        `detach=True` runs the kernel-driver detach dance immediately against
        `device` (matches what `open()` used to do inline after construction).

        `backend`, when given, is the fresh libusb1 context `open()` built
        for this device via `_fresh_libusb_backend()` (Track B) -- stashed as
        `self._backend` so `close()` can `.finalize()` it once this
        transport is done with it. `None` (the default -- what every
        existing direct-construction test uses, and what `open()` itself
        passes when no libusb1 backend could be built at all) means there is
        nothing to finalize; `close()` guards on that.
        """
        self._device = device
        self._ep_out = ep_out
        self._ep_in = ep_in
        self._backend = backend
        self._reattach_kernel_driver = False
        if detach and device.is_kernel_driver_active(0):
            device.detach_kernel_driver(0)
            self._reattach_kernel_driver = True

    @classmethod
    def open(cls, vendor_id: int = VENDOR_ID, product_id: int = PRODUCT_ID) -> "PyUsbTransport":
        """Re-enumerate and open the device. Call once per job -- no cached handles.

        Every call builds a brand-new libusb1 context via
        `_fresh_libusb_backend()` (Track B -- see that function's docstring
        for why: the stale-context half of the hotplug gap documented at
        docs/usb-setup.md §Hotplug) and passes it to `usb.core.find` as
        `backend=`, instead of relying on pyusb's own process-lifetime-cached
        backend. On EVERY failure path out of this method -- no device found,
        `set_configuration`/`claim_interface` raising (caught below, same as
        `find` itself), or the existing USBError/NoBackendError wrap -- that
        fresh backend is `.finalize()`d (guarded against `backend is None`,
        for when no libusb1 backend could be built at all) before the
        exception propagates, so a failed open never leaks a libusb context.
        On success the backend is handed to the constructor and stashed as
        `self._backend`, so `close()` finalizes it once instead (see
        `close()`).

        The whole lookup/claim sequence is wrapped: any usb.core.USBError or
        usb.core.NoBackendError (e.g. permission denied, no libusb backend
        installed) is re-raised as PrinterNotFoundError with the underlying
        message and a pointer to the udev-permissions doc, instead of
        propagating a raw pyusb traceback to the CLI (C1).
        """
        import usb.core
        import usb.util

        backend = _fresh_libusb_backend()
        try:
            device = usb.core.find(idVendor=vendor_id, idProduct=product_id, backend=backend)
            if device is None:
                if backend is not None:
                    backend.finalize()
                raise PrinterNotFoundError(
                    f"no USB printer found for vendor_id=0x{vendor_id:04x} "
                    f"product_id=0x{product_id:04x}"
                )

            transport = cls(device, detach=True, backend=backend)
            device.set_configuration()
            usb.util.claim_interface(device, 0)
            return transport
        except (usb.core.USBError, usb.core.NoBackendError) as err:
            if backend is not None:
                backend.finalize()
            raise PrinterNotFoundError(
                f"USB error opening printer: {err} — check udev permissions "
                f"(see docs/protocol-notes.md step 1)"
            ) from err

    def write(self, data: bytes, timeout_ms: int = 10000, chunk_size: int | None = None) -> None:
        usb_error, _usb_timeout_error = _usb_errors()
        try:
            for piece in _split_into_chunks(data, chunk_size):
                self._device.write(self._ep_out, piece, timeout=timeout_ms)
        except usb_error as err:
            raise TransportError(f"USB write error: {err}") from err

    def read(self, n: int, timeout_ms: int = 500) -> bytes:
        usb_error, usb_timeout_error = _usb_errors()
        try:
            data = self._device.read(self._ep_in, n, timeout=timeout_ms)
        except usb_timeout_error:
            return b""
        except usb_error as err:
            raise TransportError(f"USB read error: {err}") from err
        return bytes(data)

    def close(self) -> None:
        """Release the interface, best-effort reattach the kernel driver (both
        as before), then finalize this transport's own fresh libusb1 context
        (`self._backend`, built by `open()` via `_fresh_libusb_backend()` --
        Track B), if it has one. `.finalize()` is idempotent (pyusb's
        `AutoFinalizedObject`) and guarded against `self._backend is None`
        (the direct-construction test seam never sets one), so this is safe
        to call even when there's nothing to finalize.
        """
        import usb.util

        usb_error, _usb_timeout_error = _usb_errors()
        try:
            usb.util.release_interface(self._device, 0)
        except usb_error:
            pass
        if self._reattach_kernel_driver:
            try:
                self._device.attach_kernel_driver(0)
            except usb_error:
                pass
        if self._backend is not None:
            self._backend.finalize()
