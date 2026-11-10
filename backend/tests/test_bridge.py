"""Printer bridge (driver/bridge.py) + RemoteTransport, over a real localhost
mutual-TLS server on port 0 with per-test certificates in tmp_path
(xdist-safe, no shared state). USB is a recording CaptureTransport; the
bridge's 5s/60s timeouts are injected as milliseconds."""

from __future__ import annotations

import logging
import os
import socket
import ssl
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from labelmaker.driver import bridge as bridge_mod
from labelmaker.driver import bridge_protocol as bp
from labelmaker.driver.bridge import BridgeServer, server_context
from labelmaker.driver.bridge_identity import (
    cert_fingerprint,
    cert_pem_to_der,
    ensure_identity,
    fingerprint,
    write_pinned,
)
from labelmaker.driver.transport import (
    CaptureTransport,
    PrinterNotFoundError,
    RemoteTransport,
    TransportError,
)


class RecordingTransport(CaptureTransport):
    def __init__(self) -> None:
        super().__init__()
        self.closed = False

    def close(self) -> None:
        self.closed = True


def wait_for(cond, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.005)
    return cond()


class Env:
    """A paired app + bridge pair of identities and a running server."""

    def __init__(self, tmp_path: Path, **server_kwargs) -> None:
        self.bridge_key, self.bridge_cert = ensure_identity(tmp_path / "bridge", "bridge")
        self.app_key, self.app_cert = ensure_identity(tmp_path / "app", "client")
        self.other_key, self.other_cert = ensure_identity(tmp_path / "other", "client")
        self.bridge_pem = self.bridge_cert.read_text()
        self.app_pem = self.app_cert.read_text()
        self.transports: list[RecordingTransport] = []
        self.open_error: Exception | None = None
        self.server = BridgeServer(
            server_context(self.bridge_cert, self.bridge_key, self.app_pem),
            cert_fingerprint(self.app_pem),
            host="127.0.0.1",
            port=0,
            opener=self._opener,
            **server_kwargs,
        )
        self.server.start()

    def _opener(self):
        if self.open_error is not None:
            raise self.open_error
        transport = RecordingTransport()
        self.transports.append(transport)
        return transport

    @property
    def address(self) -> str:
        return f"127.0.0.1:{self.server.port}"

    def client(self, *, key=None, cert=None, pinned=None, **kwargs) -> RemoteTransport:
        return RemoteTransport.open(
            self.address,
            key or self.app_key,
            cert or self.app_cert,
            pinned or self.bridge_pem,
            **kwargs,
        )

    def raw_tls(self, *, with_cert=True, max_version=None) -> ssl.SSLSocket:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.load_verify_locations(cadata=self.bridge_pem)
        if with_cert:
            ctx.load_cert_chain(self.app_cert, self.app_key)
        if max_version is not None:
            ctx.maximum_version = max_version
        raw = socket.create_connection(("127.0.0.1", self.server.port), timeout=3)
        return ctx.wrap_socket(raw)


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path, handshake_timeout=0.3, idle_timeout=5, busy_wait=0.2)
    yield e
    e.server.stop()


# -- protocol helpers ---------------------------------------------------------


def test_parse_address():
    assert bp.parse_address("pi.local") == ("pi.local", 9177)
    assert bp.parse_address("10.0.0.5:1234") == ("10.0.0.5", 1234)
    assert bp.parse_address("[fe80::1]") == ("fe80::1", 9177)
    assert bp.parse_address("[fe80::1]:99") == ("fe80::1", 99)
    assert bp.parse_address("fe80::1") == ("fe80::1", 9177)
    for bad in ("", "host:0", "host:70000", "host:abc", "[::1", "[::1]x", "a b", ":80"):
        with pytest.raises(ValueError):
            bp.parse_address(bad)


def test_recv_exact_handles_partial_reads():
    class Drip:
        def __init__(self, data: bytes) -> None:
            self.data = data

        def recv_into(self, view, n):
            view[:1] = self.data[:1]
            self.data = self.data[1:]
            return 1 if n else 0

    assert bp.recv_exact(Drip(b"abcdef"), 6) == b"abcdef"


def test_bridge_module_does_not_import_fastapi():
    code = (
        "import sys, labelmaker.driver.bridge; "
        "sys.exit(1 if 'fastapi' in sys.modules or 'cryptography' in sys.modules else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code], timeout=60).returncode == 0


# -- identity -----------------------------------------------------------------


def test_key_file_is_0600_and_cert_not_a_key(tmp_path):
    key, cert = ensure_identity(tmp_path / "id", "client")
    assert stat.S_IMODE(os.stat(key).st_mode) == 0o600
    assert "PRIVATE KEY" in key.read_text()
    assert "PRIVATE KEY" not in cert.read_text()
    assert list((tmp_path / "id").glob(".*")) == []  # temp names cleaned up


def test_concurrent_first_use_yields_one_matching_identity(tmp_path):
    results: list[tuple[bytes, bytes]] = []

    def go():
        key, cert = ensure_identity(tmp_path / "id", "client")
        results.append((key.read_bytes(), cert.read_bytes()))

    threads = [threading.Thread(target=go) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(results)) == 1


def test_cert_validation(tmp_path):
    _key, cert = ensure_identity(tmp_path / "id", "client")
    pem = cert.read_text()
    assert len(cert_pem_to_der(pem)) > 100
    with pytest.raises(ValueError, match="private key"):
        cert_pem_to_der(pem + (tmp_path / "id" / "client.key").read_text())
    with pytest.raises(ValueError, match="exactly one"):
        cert_pem_to_der(pem + pem)
    with pytest.raises(ValueError):
        cert_pem_to_der("-----BEGIN CERTIFICATE-----\nnope\n-----END CERTIFICATE-----\n")
    with pytest.raises(ValueError):
        cert_pem_to_der("hello")


def test_write_pinned_is_atomic_and_validated(tmp_path):
    _key, cert = ensure_identity(tmp_path / "id", "client")
    fp = write_pinned(tmp_path / "pins" / "app.crt", cert.read_text())
    assert fp == cert_fingerprint(cert.read_text())
    with pytest.raises(ValueError):
        write_pinned(tmp_path / "pins" / "bad.crt", "junk")
    assert not (tmp_path / "pins" / "bad.crt").exists()


# -- happy path ---------------------------------------------------------------


def test_write_read_round_trip(env):
    client = env.client()
    transport = env.transports[0]
    transport.queue_read(b"\x01\x02")
    client.write(b"hello")
    assert client.read(32) == b"\x01\x02"
    assert client.read(32) == b""
    client.close()
    assert transport.written == b"hello"
    assert wait_for(lambda: transport.closed)


def test_chunked_write_is_split_and_acknowledged(env):
    client = env.client()
    client.write(b"0123456789", chunk_size=4)
    assert env.transports[0].writes_list == [b"0123", b"4567", b"89"]
    client.close()


def test_write_larger_than_frame_cap_is_split_even_without_chunk_size(env, monkeypatch):
    monkeypatch.setattr(bp, "MAX_FRAME", 12)  # 8 bytes of data per frame
    client = env.client()
    client.write(b"x" * 20)
    assert [len(w) for w in env.transports[0].writes_list] == [8, 8, 4]
    client.close()


# -- security: nothing reaches USB without a valid pinned client --------------


def _assert_rejected(env, attempt):
    with pytest.raises((OSError, ssl.SSLError, bp.ProtocolError, PrinterNotFoundError)):
        attempt()
    assert env.transports == []


def test_client_without_certificate_is_rejected(env):
    def attempt():
        s = env.raw_tls(with_cert=False)
        bp.send_frame(s, bp.OP_HELLO, bytes([bp.PROTOCOL_VERSION]))
        bp.recv_frame(s)

    _assert_rejected(env, attempt)


def test_unpinned_client_certificate_is_rejected(env):
    _assert_rejected(env, lambda: env.client(key=env.other_key, cert=env.other_cert))


def test_plaintext_client_is_dropped_and_server_keeps_serving(env):
    s = socket.create_connection(("127.0.0.1", env.server.port), timeout=3)
    s.sendall(b"\x01\x00\x00\x00\x01\x01")
    s.settimeout(3)
    try:
        s.recv(100)  # dropped (EOF) or a TLS alert; either way no protocol reply
    except OSError:
        pass
    s.close()
    assert env.transports == []
    env.client().close()


def test_stalled_handshake_does_not_block_others_and_is_dropped(env):
    stalled = socket.create_connection(("127.0.0.1", env.server.port), timeout=3)
    env.client().close()  # accept loop and other connections unaffected
    stalled.settimeout(3)
    try:
        assert stalled.recv(1) == b""  # server hung up after handshake_timeout
    except ConnectionError:
        pass
    stalled.close()
    assert len(env.transports) == 1  # only the legitimate client opened USB


def test_connect_without_handshake_logs_no_warning(env, caplog):
    caplog.set_level(logging.DEBUG, logger="labelmaker.bridge")
    socket.create_connection(("127.0.0.1", env.server.port), timeout=3).close()
    deadline = time.monotonic() + 3
    while "closed before the TLS handshake" not in caplog.text:
        assert time.monotonic() < deadline, caplog.text
        time.sleep(0.01)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_client_rejects_unpinned_server_certificate(env):
    with pytest.raises(PrinterNotFoundError, match="does not match") as exc_info:
        env.client(pinned=env.app_pem)  # any cert other than the bridge's
    assert exc_info.value.code == "bridge_cert_mismatch"


def test_tls_1_2_is_refused(env):
    def attempt():
        env.raw_tls(max_version=ssl.TLSVersion.TLSv1_2)

    _assert_rejected(env, attempt)


def test_unpaired_app_gets_a_not_paired_error(env):
    with pytest.raises(PrinterNotFoundError, match="not\n?.*paired") as exc_info:
        env.client(key=env.other_key, cert=env.other_cert)
    assert exc_info.value.code == "bridge_unpaired"


# -- protocol errors ----------------------------------------------------------


def test_version_mismatch(env):
    s = env.raw_tls()
    bp.send_frame(s, bp.OP_HELLO, bytes([99]))
    kind, payload = bp.recv_frame(s)
    assert kind == bp.REPLY_ERR and bp.parse_err(payload)[0] == bp.ERR_VERSION
    s.close()
    assert env.transports == []


def test_oversized_frame_is_refused_before_reading_it(env):
    s = env.raw_tls()
    bp.send_frame(s, bp.OP_HELLO, bytes([bp.PROTOCOL_VERSION]))
    bp.recv_frame(s)
    s.sendall(bytes([bp.OP_WRITE]) + (bp.MAX_FRAME + 1).to_bytes(4, "big"))  # no payload follows
    kind, payload = bp.recv_frame(s)
    assert kind == bp.REPLY_ERR and bp.parse_err(payload)[0] == bp.ERR_PROTOCOL
    s.close()


def test_open_required_before_write(env):
    s = env.raw_tls()
    bp.send_frame(s, bp.OP_HELLO, bytes([bp.PROTOCOL_VERSION]))
    bp.recv_frame(s)
    bp.send_frame(s, bp.OP_WRITE, b"\0\0\0\1x")
    kind, payload = bp.recv_frame(s)
    assert kind == bp.REPLY_ERR and bp.parse_err(payload)[0] == bp.ERR_PROTOCOL
    s.close()
    assert env.transports == []


def test_not_found_maps_to_printer_not_found(env):
    env.open_error = PrinterNotFoundError("no USB printer found")
    with pytest.raises(PrinterNotFoundError, match="no USB printer found"):
        env.client()
    env.open_error = None
    env.client().close()  # the session slot was released


def test_busy_second_client(env):
    first = env.client()
    with pytest.raises(PrinterNotFoundError, match="another client"):
        env.client()
    first.close()
    assert wait_for(lambda: env.transports[0].closed)
    env.client().close()


def test_idle_timeout_closes_usb_and_frees_the_slot(tmp_path):
    e = Env(tmp_path, handshake_timeout=1, idle_timeout=0.2, busy_wait=0.2)
    try:
        client = e.client()
        assert wait_for(lambda: e.transports[0].closed)
        with pytest.raises(TransportError):
            client.write(b"x")
        e.client().close()
    finally:
        e.server.stop()


def test_usb_closed_when_client_disconnects_abruptly(env):
    client = env.client()
    client._sock.close()  # no CLOSE frame
    assert wait_for(lambda: env.transports[0].closed)
    env.client().close()


# -- error mapping ------------------------------------------------------------


def test_unreachable_bridge_is_printer_not_found(env, tmp_path):
    port = env.server.port
    env.server.stop()
    with pytest.raises(PrinterNotFoundError, match="cannot reach"):
        RemoteTransport.open(
            f"127.0.0.1:{port}", env.app_key, env.app_cert, env.bridge_pem, connect_timeout=0.5
        )


def test_usb_error_on_bridge_is_transport_error(env):
    client = env.client()

    def boom(*_a, **_k):
        raise TransportError("USB write error: pipe")

    env.transports[0].write = boom
    with pytest.raises(TransportError, match="pipe"):
        client.write(b"x")
    client.close()


def test_server_dying_mid_session_is_transport_error(env):
    client = env.client()
    env.server.stop()
    with pytest.raises(TransportError):
        client.write(b"x")
    with pytest.raises(TransportError):
        client.read(1)  # stays failed
    client.close()  # never raises


def test_a_failed_write_is_never_sent_twice(env):
    client = env.client()
    calls = []

    def flaky(data, timeout_ms=10000, chunk_size=None):
        calls.append(bytes(data))
        raise TransportError("USB write error")

    env.transports[0].write = flaky
    with pytest.raises(TransportError):
        client.write(b"label")
    assert calls == [b"label"]
    client.close()


# -- CLI ----------------------------------------------------------------------


def test_serve_refuses_to_start_unpaired(tmp_path, capsys):
    assert bridge_mod.main(["--dir", str(tmp_path), "serve"]) == 2
    assert "not paired" in capsys.readouterr().err


def test_show_cert_and_pair(tmp_path, capsys):
    _k, app_cert = ensure_identity(tmp_path / "app", "client")
    d = str(tmp_path / "bridge")
    assert bridge_mod.main(["--dir", d, "show-cert"]) == 0
    out = capsys.readouterr()
    assert out.out.startswith("-----BEGIN CERTIFICATE-----")
    assert "PRIVATE KEY" not in out.out
    assert bridge_mod.main(["--dir", d, "pair", str(app_cert)]) == 0
    pinned = (tmp_path / "bridge" / "app.crt").read_text()
    assert fingerprint(cert_pem_to_der(pinned)) == cert_fingerprint(app_cert.read_text())
    bad = tmp_path / "bad.pem"
    bad.write_text("nope")
    assert bridge_mod.main(["--dir", d, "pair", str(bad)]) == 2


def test_cli_remote_flags_reach_the_bridge(tmp_path, capsys):
    from labelmaker.driver import cli
    from labelmaker.driver.transport import MockPrinterTransport

    data_dir = tmp_path / "data"
    _k, app_cert = ensure_identity(data_dir / "bridge", "client")  # the CLI's identity
    b_key, b_cert = ensure_identity(tmp_path / "bridge", "bridge")
    server = BridgeServer(
        server_context(b_cert, b_key, app_cert.read_text()),
        cert_fingerprint(app_cert.read_text()),
        host="127.0.0.1",
        port=0,
        opener=MockPrinterTransport,
    )
    server.start()
    try:
        argv = [
            "--remote", f"127.0.0.1:{server.port}",
            "--bridge-cert", str(b_cert),
            "--data-dir", str(data_dir),
            "status",
        ]  # fmt: skip
        assert cli.main(argv) == 0
        assert "Media width: 24mm" in capsys.readouterr().out
    finally:
        server.stop()
        cli._remote_settings = None


def test_cli_remote_requires_bridge_cert():
    from labelmaker.driver import cli

    with pytest.raises(SystemExit):
        cli.main(["--remote", "pi.local", "status"])
