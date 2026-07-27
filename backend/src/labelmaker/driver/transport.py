"""Wire transports for the PT-E720BT: real USB bulk transfer and an in-memory
test double.

`usb.core` / `usb.util` are imported lazily -- inside methods, never at
module import time -- so that importing this module, using `CaptureTransport`
(the test double and the `PRINTER_MODE=mock` backend), and running the test
suite / CI never require libusb to be installed.
"""

from typing import Protocol


class PrinterNotFoundError(Exception):
    """Raised when PyUsbTransport.open() finds no matching USB device."""


class Transport(Protocol):
    def write(self, data: bytes) -> None: ...

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

    def write(self, data: bytes) -> None:
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


class PyUsbTransport:
    """Real USB bulk transport. Opened fresh per print job -- callers re-open
    on every job rather than caching a device handle across power cycles; no
    reconnect logic here by design.
    """

    VENDOR_ID = 0x04F9
    PRODUCT_ID = 0x224A
    EP_OUT = 0x02
    EP_IN = 0x81

    def __init__(self, device, ep_out: int = EP_OUT, ep_in: int = EP_IN) -> None:
        self._device = device
        self._ep_out = ep_out
        self._ep_in = ep_in
        self._reattach_kernel_driver = False

    @classmethod
    def open(cls, vendor_id: int = VENDOR_ID, product_id: int = PRODUCT_ID) -> "PyUsbTransport":
        """Re-enumerate and open the device. Call once per job -- no cached handles."""
        import usb.core
        import usb.util

        device = usb.core.find(idVendor=vendor_id, idProduct=product_id)
        if device is None:
            raise PrinterNotFoundError(
                f"no USB printer found for vendor_id=0x{vendor_id:04x} "
                f"product_id=0x{product_id:04x}"
            )

        transport = cls(device)
        if device.is_kernel_driver_active(0):
            device.detach_kernel_driver(0)
            transport._reattach_kernel_driver = True
        device.set_configuration()
        usb.util.claim_interface(device, 0)
        return transport

    def write(self, data: bytes) -> None:
        self._device.write(self._ep_out, data)

    def read(self, n: int, timeout_ms: int = 500) -> bytes:
        import usb.core

        try:
            data = self._device.read(self._ep_in, n, timeout=timeout_ms)
        except usb.core.USBTimeoutError:
            return b""
        return bytes(data)

    def close(self) -> None:
        import usb.core
        import usb.util

        try:
            usb.util.release_interface(self._device, 0)
        except usb.core.USBError:
            pass
        if self._reattach_kernel_driver:
            try:
                self._device.attach_kernel_driver(0)
            except usb.core.USBError:
                pass
