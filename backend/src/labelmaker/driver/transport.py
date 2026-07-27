"""Wire transports for the PT-E720BT: real USB bulk transfer and an in-memory
test double.

`usb.core` / `usb.util` are imported lazily -- inside methods, never at
module import time -- so that importing this module, using `CaptureTransport`
(the test double and the `PRINTER_MODE=mock` backend), and running the test
suite / CI never require libusb to be installed.
"""

from typing import Protocol


class PrinterNotFoundError(Exception):
    """Raised when PyUsbTransport.open() finds no matching USB device, or when
    opening the device fails outright (a wrapped usb.core.USBError/NoBackendError).
    """


class TransportError(Exception):
    """Raised when a USB read or write fails for a reason other than a timeout
    (timeouts are not errors -- read() returns b"" instead, per the Transport
    protocol).
    """


class Transport(Protocol):
    def write(self, data: bytes, timeout_ms: int = 10000) -> None: ...

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

    def write(self, data: bytes, timeout_ms: int = 10000) -> None:
        # timeout_ms is part of the Transport protocol (I2) but meaningless
        # for an in-memory double -- accepted and ignored.
        self.written.extend(data)
        self.writes_list.append(bytes(data))

    def queue_read(self, data: bytes) -> None:
        """Queue one scripted reply. Each read() call pops the next one, FIFO."""
        self._read_queue.append(data)

    def read(self, n: int, timeout_ms: int = 500) -> bytes:
        if not self._read_queue:
            return b""
        return self._read_queue.pop(0)

    def close(self) -> None:
        pass


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


class PyUsbTransport:
    """Real USB bulk transport. Opened fresh per print job -- callers re-open
    on every job rather than caching a device handle across power cycles; no
    reconnect logic here by design.
    """

    VENDOR_ID = 0x04F9
    PRODUCT_ID = 0x224A
    EP_OUT = 0x02
    EP_IN = 0x81

    def __init__(
        self, device, ep_out: int = EP_OUT, ep_in: int = EP_IN, *, detach: bool = False
    ) -> None:
        """Wrap an already-found device. `open()` is the production entry point
        (real pyusb lookup + interface claim); this constructor is also a
        documented **test seam**: tests call `PyUsbTransport(device=fake,
        detach=...)` directly with a minimal duck-typed fake device object,
        bypassing pyusb/usb.core entirely (see test_transport.py).

        `detach=True` runs the kernel-driver detach dance immediately against
        `device` (matches what `open()` used to do inline after construction).
        """
        self._device = device
        self._ep_out = ep_out
        self._ep_in = ep_in
        self._reattach_kernel_driver = False
        if detach and device.is_kernel_driver_active(0):
            device.detach_kernel_driver(0)
            self._reattach_kernel_driver = True

    @classmethod
    def open(cls, vendor_id: int = VENDOR_ID, product_id: int = PRODUCT_ID) -> "PyUsbTransport":
        """Re-enumerate and open the device. Call once per job -- no cached handles.

        The whole lookup/claim sequence is wrapped: any usb.core.USBError or
        usb.core.NoBackendError (e.g. permission denied, no libusb backend
        installed) is re-raised as PrinterNotFoundError with the underlying
        message and a pointer to the udev-permissions doc, instead of
        propagating a raw pyusb traceback to the CLI (C1).
        """
        import usb.core
        import usb.util

        try:
            device = usb.core.find(idVendor=vendor_id, idProduct=product_id)
            if device is None:
                raise PrinterNotFoundError(
                    f"no USB printer found for vendor_id=0x{vendor_id:04x} "
                    f"product_id=0x{product_id:04x}"
                )

            transport = cls(device, detach=True)
            device.set_configuration()
            usb.util.claim_interface(device, 0)
            return transport
        except (usb.core.USBError, usb.core.NoBackendError) as err:
            raise PrinterNotFoundError(
                f"USB error opening printer: {err} — check udev permissions "
                f"(see docs/protocol-notes.md step 1)"
            ) from err

    def write(self, data: bytes, timeout_ms: int = 10000) -> None:
        usb_error, _usb_timeout_error = _usb_errors()
        try:
            self._device.write(self._ep_out, data, timeout=timeout_ms)
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
