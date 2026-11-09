"""Raspberry Pi printer bridge: owns the USB connection and serves it over
mutual TLS to the app's `RemoteTransport`.

    python -m labelmaker.driver.bridge serve | show-cert | pair <file or ->

Env: BRIDGE_PORT (default 9177), BRIDGE_DIR (default /data: bridge key,
certificate and the pinned app certificate), BRIDGE_HOST (default 0.0.0.0).

Stdlib only at import time (no FastAPI). One TLS connection = one USB
session, one session at a time. Nothing speaks the protocol or touches USB
until the handshake and the certificate pin check pass.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import ssl
import struct
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from labelmaker.driver import bridge_protocol as bp
from labelmaker.driver.transport import PrinterNotFoundError, Transport, TransportError

logger = logging.getLogger("labelmaker.bridge")

HANDSHAKE_TIMEOUT_S = 5.0
IDLE_TIMEOUT_S = 60.0
BUSY_WAIT_S = 5.0
BRIDGE_STEM = "bridge"
PINNED_APP_CERT = "app.crt"


def server_context(cert_path: Path, key_path: Path, pinned_pem: str) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_cert_chain(str(cert_path), str(key_path))
    ctx.load_verify_locations(cadata=pinned_pem)
    return ctx


def _default_opener() -> Transport:
    from labelmaker.driver.transport import PyUsbTransport

    return PyUsbTransport.open()


class BridgeServer:
    """TLS server. `opener` is the USB seam (tests inject a CaptureTransport);
    the timeouts are injectable so tests run in milliseconds."""

    def __init__(
        self,
        context: ssl.SSLContext,
        pinned_fingerprint: str,
        *,
        host: str = "0.0.0.0",
        port: int = bp.DEFAULT_PORT,
        opener: Callable[[], Transport] = _default_opener,
        handshake_timeout: float = HANDSHAKE_TIMEOUT_S,
        idle_timeout: float = IDLE_TIMEOUT_S,
        busy_wait: float = BUSY_WAIT_S,
    ) -> None:
        self._ctx = context
        self._pin = pinned_fingerprint
        self._opener = opener
        self._handshake_timeout = handshake_timeout
        self._idle_timeout = idle_timeout
        self._busy_wait = busy_wait
        self._slot = threading.Lock()
        self._stopping = threading.Event()
        self._conns: set[socket.socket] = set()
        self._conns_lock = threading.Lock()
        self._threads: set[threading.Thread] = set()
        self._listener = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind((host, port))
        self._listener.listen(16)
        self.port: int = self._listener.getsockname()[1]
        self._accept_thread: threading.Thread | None = None

    def start(self) -> None:
        self._accept_thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._accept_thread.start()

    def serve_forever(self) -> None:
        while not self._stopping.is_set():
            try:
                conn, peer = self._listener.accept()
            except OSError:
                break
            thread = threading.Thread(target=self._handle, args=(conn, peer), daemon=True)
            with self._conns_lock:
                self._conns.add(conn)
                self._threads.add(thread)
            thread.start()

    def stop(self) -> None:
        self._stopping.set()
        try:
            self._listener.shutdown(socket.SHUT_RDWR)  # wakes a blocked accept()
        except OSError:
            pass
        try:
            self._listener.close()
        except OSError:
            pass
        with self._conns_lock:
            conns, threads = list(self._conns), list(self._threads)
        for conn in conns:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=2)
        for thread in threads:
            thread.join(timeout=2)

    # -- per connection -----------------------------------------------------

    def _handle(self, raw: socket.socket, peer) -> None:
        conn: socket.socket = raw
        try:
            raw.settimeout(self._handshake_timeout)
            conn = self._ctx.wrap_socket(raw, server_side=True, do_handshake_on_connect=False)
            with self._conns_lock:  # wrap_socket detached `raw`; track the live socket
                self._conns.discard(raw)
                self._conns.add(conn)
            conn.do_handshake()
            der = conn.getpeercert(binary_form=True)
            from labelmaker.driver.bridge_identity import fingerprint

            if not der or fingerprint(der) != self._pin:
                logger.warning(
                    "rejected client certificate %s from %s",
                    fingerprint(der) if der else "(none)",
                    peer[0],
                )
                return
            conn.settimeout(self._idle_timeout)
            logger.info("client connected from %s", peer[0])
            self._session(conn)
        except ssl.SSLEOFError:
            # Connected and left without a handshake: the compose healthcheck
            # does this every 30s, so a warning would bury real rejections.
            logger.debug("connection from %s closed before the TLS handshake", peer[0])
        except ssl.SSLError as err:
            logger.warning("TLS handshake with %s failed (unpaired certificate?): %s", peer[0], err)
        except (OSError, bp.ProtocolError) as err:
            logger.info("connection from %s ended: %s", peer[0], err)
        except Exception:
            logger.exception("unexpected error serving %s", peer[0])
        finally:
            try:
                conn.close()
            except OSError:
                pass
            with self._conns_lock:
                self._conns.discard(raw)
                self._conns.discard(conn)
                self._threads.discard(threading.current_thread())

    def _session(self, conn: socket.socket) -> None:
        transport: Transport | None = None
        have_slot = False
        try:
            hello = True
            while True:
                try:
                    op, payload = bp.recv_frame(conn)
                except bp.ProtocolError as err:
                    self._err(conn, bp.ERR_PROTOCOL, str(err))
                    return
                if hello:
                    if op != bp.OP_HELLO or len(payload) != 1:
                        self._err(conn, bp.ERR_PROTOCOL, "expected HELLO")
                        return
                    if payload[0] != bp.PROTOCOL_VERSION:
                        self._err(
                            conn,
                            bp.ERR_VERSION,
                            f"bridge speaks protocol {bp.PROTOCOL_VERSION}, client {payload[0]}",
                        )
                        return
                    hello = False
                    bp.send_frame(conn, bp.REPLY_OK)
                elif op == bp.OP_OPEN:
                    if have_slot:
                        self._err(conn, bp.ERR_PROTOCOL, "session already open")
                        continue
                    if not self._slot.acquire(timeout=self._busy_wait):
                        self._err(conn, bp.ERR_BUSY, "bridge is serving another client")
                        return
                    have_slot = True
                    try:
                        transport = self._opener()
                    except PrinterNotFoundError as err:
                        have_slot = False
                        self._slot.release()
                        self._err(conn, bp.ERR_NOT_FOUND, str(err))
                        return
                    except Exception as err:
                        have_slot = False
                        self._slot.release()
                        self._err(conn, bp.ERR_TRANSPORT, f"USB open failed: {err}")
                        return
                    bp.send_frame(conn, bp.REPLY_OK)
                elif op == bp.OP_CLOSE:
                    bp.send_frame(conn, bp.REPLY_OK)
                    return
                elif transport is None:
                    self._err(conn, bp.ERR_PROTOCOL, "OPEN first")
                    return
                elif op == bp.OP_WRITE:
                    if len(payload) < bp.WRITE_HEADER_LEN:
                        self._err(conn, bp.ERR_PROTOCOL, "short WRITE")
                        return
                    (timeout_ms,) = struct.unpack_from("!I", payload)
                    self._usb_write(conn, transport, payload[bp.WRITE_HEADER_LEN :], timeout_ms)
                elif op == bp.OP_READ:
                    if len(payload) != 8:
                        self._err(conn, bp.ERR_PROTOCOL, "bad READ")
                        return
                    n, timeout_ms = struct.unpack("!II", payload)
                    if n > bp.MAX_FRAME:
                        self._err(conn, bp.ERR_PROTOCOL, "READ too large")
                        return
                    self._usb_read(conn, transport, n, timeout_ms)
                else:
                    self._err(conn, bp.ERR_PROTOCOL, f"unknown op {op}")
                    return
        finally:
            if transport is not None:
                try:
                    transport.close()
                except Exception:
                    logger.exception("error closing USB transport")
            if have_slot:
                self._slot.release()

    @staticmethod
    def _usb_write(conn: socket.socket, transport: Transport, data: bytes, timeout_ms: int) -> None:
        try:
            transport.write(data, timeout_ms)
        except (TransportError, OSError) as err:
            logger.warning("USB write error: %s", err)
            BridgeServer._err(conn, bp.ERR_TRANSPORT, str(err))
            return
        bp.send_frame(conn, bp.REPLY_OK)

    @staticmethod
    def _usb_read(conn: socket.socket, transport: Transport, n: int, timeout_ms: int) -> None:
        try:
            data = transport.read(n, timeout_ms)
        except (TransportError, OSError) as err:
            logger.warning("USB read error: %s", err)
            BridgeServer._err(conn, bp.ERR_TRANSPORT, str(err))
            return
        bp.send_frame(conn, bp.REPLY_OK, data)

    @staticmethod
    def _err(conn: socket.socket, code: int, message: str) -> None:
        try:
            bp.send_frame(conn, bp.REPLY_ERR, bp.err_payload(code, message))
        except OSError:
            pass


# -- CLI ----------------------------------------------------------------------


def _bridge_dir() -> Path:
    return Path(os.environ.get("BRIDGE_DIR", "/data"))


def _cmd_show_cert(_args: argparse.Namespace) -> int:
    from labelmaker.driver.bridge_identity import cert_fingerprint, ensure_identity

    _key, cert = ensure_identity(_bridge_dir(), BRIDGE_STEM)
    pem = cert.read_text()
    sys.stdout.write(pem)
    print(f"sha256 fingerprint: {cert_fingerprint(pem)}", file=sys.stderr)
    return 0


def _cmd_pair(args: argparse.Namespace) -> int:
    from labelmaker.driver.bridge_identity import write_pinned

    text = sys.stdin.read() if args.cert == "-" else Path(args.cert).read_text()
    try:
        fp = write_pinned(_bridge_dir() / PINNED_APP_CERT, text)
    except ValueError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    print(f"paired with app certificate sha256 {fp}; restart the bridge to apply", file=sys.stderr)
    return 0


def _cmd_serve(_args: argparse.Namespace) -> int:
    from labelmaker.driver.bridge_identity import cert_fingerprint, ensure_identity

    directory = _bridge_dir()
    pin_path = directory / PINNED_APP_CERT
    if not pin_path.is_file():
        print(
            f"error: not paired: {pin_path} is missing. Run `show-cert`, enter it in the app, "
            "then `pair` the app's certificate.",
            file=sys.stderr,
        )
        return 2
    pinned = pin_path.read_text()
    try:
        pin_fp = cert_fingerprint(pinned)
    except ValueError as err:
        print(f"error: {pin_path} is not a valid certificate: {err}", file=sys.stderr)
        return 2
    key, cert = ensure_identity(directory, BRIDGE_STEM)
    server = BridgeServer(
        server_context(cert, key, pinned),
        pin_fp,
        host=os.environ.get("BRIDGE_HOST", "0.0.0.0"),
        port=int(os.environ.get("BRIDGE_PORT", bp.DEFAULT_PORT)),
    )
    signal.signal(signal.SIGTERM, lambda *_: server.stop())
    logger.info("bridge listening on port %d, paired with app %s", server.port, pin_fp)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="labelmaker.driver.bridge")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="run the bridge").set_defaults(func=_cmd_serve)
    sub.add_parser("show-cert", help="print this bridge's certificate").set_defaults(
        func=_cmd_show_cert
    )
    pair = sub.add_parser("pair", help="pin the app's certificate")
    pair.add_argument("cert", help="certificate file, or - for stdin")
    pair.set_defaults(func=_cmd_pair)
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
