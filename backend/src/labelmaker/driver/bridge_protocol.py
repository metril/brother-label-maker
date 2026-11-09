"""Wire protocol between the app's `RemoteTransport` and the Pi-side bridge
(`bridge.py`). Stdlib only, so the bridge never pulls in FastAPI.

Framing, inside TLS: `[op:u8][len:u32be][payload]`, payload capped at
MAX_FRAME. Replies are OK(payload) or ERR(code:u8 + utf-8 message).
"""

from __future__ import annotations

import socket
import struct

PROTOCOL_VERSION = 1
DEFAULT_PORT = 9177
MAX_FRAME = 16 * 1024 * 1024

OP_HELLO = 1  # payload: version:u8
OP_OPEN = 2  # payload: empty
OP_WRITE = 3  # payload: timeout_ms:u32 + data
OP_READ = 4  # payload: n:u32 + timeout_ms:u32
OP_CLOSE = 5  # payload: empty
REPLY_OK = 0x80
REPLY_ERR = 0x81

ERR_NOT_FOUND = 1
ERR_TRANSPORT = 2
ERR_BUSY = 3
ERR_VERSION = 4
ERR_PROTOCOL = 5  # malformed or oversized frame, unknown op, wrong state

_HEADER = struct.Struct("!BI")
WRITE_HEADER_LEN = 4  # timeout_ms prefix inside a WRITE payload


class ProtocolError(Exception):
    """Malformed, oversized or truncated frame."""


def parse_address(address: str) -> tuple[str, int]:
    """`host`, `host:port`, `[v6]`, `[v6]:port` or a bare IPv6 literal ->
    (host, port); the port defaults to DEFAULT_PORT. Raises ValueError."""
    value = address.strip()
    if not value or any(ch.isspace() for ch in value):
        raise ValueError("bridge address must be host or host:port, without spaces")
    port_text: str | None = None
    if value.startswith("["):
        host, sep, rest = value[1:].partition("]")
        if not sep or not host:
            raise ValueError("bridge address has an unterminated [ipv6] bracket")
        if rest:
            if not rest.startswith(":"):
                raise ValueError("bridge address: expected :port after the closing bracket")
            port_text = rest[1:]
    elif value.count(":") == 1:
        host, _, port_text = value.partition(":")
    else:
        host = value  # hostname/IPv4 without a port, or a bare IPv6 literal
    if not host:
        raise ValueError("bridge address has an empty host")
    if port_text is None:
        return host, DEFAULT_PORT
    if not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
        raise ValueError("bridge address port must be a number between 1 and 65535")
    return host, int(port_text)


def recv_exact(sock: socket.socket, n: int) -> bytes:
    """Read exactly n bytes, looping over partial reads."""
    buf = bytearray(n)
    view = memoryview(buf)
    got = 0
    while got < n:
        chunk = sock.recv_into(view[got:], n - got)
        if chunk == 0:
            raise ConnectionError("peer closed the connection")
        got += chunk
    return bytes(buf)


def send_frame(sock: socket.socket, op: int, payload: bytes = b"") -> None:
    if len(payload) > MAX_FRAME:
        raise ProtocolError(f"frame payload {len(payload)} exceeds {MAX_FRAME}")
    sock.sendall(_HEADER.pack(op, len(payload)) + payload)


def recv_frame(sock: socket.socket) -> tuple[int, bytes]:
    """Read one frame. The length is checked against MAX_FRAME before any
    payload buffer is allocated."""
    op, length = _HEADER.unpack(recv_exact(sock, _HEADER.size))
    if length > MAX_FRAME:
        raise ProtocolError(f"frame length {length} exceeds {MAX_FRAME}")
    return op, recv_exact(sock, length) if length else b""


def err_payload(code: int, message: str) -> bytes:
    return bytes([code]) + message.encode("utf-8", "replace")[:1000]


def parse_err(payload: bytes) -> tuple[int, str]:
    if not payload:
        return ERR_PROTOCOL, "empty error reply"
    return payload[0], payload[1:].decode("utf-8", "replace")
