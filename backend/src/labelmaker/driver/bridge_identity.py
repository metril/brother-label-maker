"""Self-signed identity certificates for the printer bridge's mutual TLS.

Each side (the app, the bridge) owns one ECDSA P-256 key + self-signed
CA:FALSE certificate and pins the other side's certificate. `cryptography`
is imported lazily inside the functions that need it, so the plain USB/mock
paths and the Pi bridge's fast paths never pay for it.
"""

from __future__ import annotations

import hashlib
import os
import threading
import uuid
from pathlib import Path

_BEGIN = "-----BEGIN CERTIFICATE-----"
_VALID_DAYS = 36500  # ~100 years
_IDENTITY_LOCK = threading.Lock()


def fingerprint(der: bytes) -> str:
    """SHA-256 of a DER certificate, lowercase hex."""
    return hashlib.sha256(der).hexdigest()


def cert_pem_to_der(pem: str) -> bytes:
    """Validate that `pem` is exactly one X.509 certificate (and never a
    private key) and return its DER. Raises ValueError without echoing the
    input."""
    if "PRIVATE KEY" in pem:
        raise ValueError("this looks like a private key; paste only the public certificate")
    if pem.count(_BEGIN) != 1:
        raise ValueError("expected exactly one PEM certificate")
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding

    try:
        cert = x509.load_pem_x509_certificate(pem.strip().encode("ascii"))
    except (ValueError, UnicodeEncodeError) as err:
        raise ValueError("not a valid PEM X.509 certificate") from err
    return cert.public_bytes(Encoding.DER)


def cert_fingerprint(pem: str) -> str:
    return fingerprint(cert_pem_to_der(pem))


def _write_new(path: Path, data: bytes, mode: int) -> None:
    """Create `path` with `mode` from the first byte (O_EXCL, no chmod)."""
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


def _build_cert(key, common_name: str) -> bytes:
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.serialization import Encoding
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=_VALID_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage(
                [ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(Encoding.PEM)


def ensure_identity(directory: Path, stem: str) -> tuple[Path, Path]:
    """Return (key_path, cert_path) for `<directory>/<stem>.{key,crt}`,
    generating them on first use.

    Safe against concurrent first calls (threads or processes): the key is
    published with an atomic link() (first writer wins, mode 0600 from
    creation), and the certificate is always derived from whichever key is
    on disk, also published with link(), so key and certificate can never
    mismatch.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    key_path = directory / f"{stem}.key"
    cert_path = directory / f"{stem}.crt"
    with _IDENTITY_LOCK:
        if not key_path.exists():
            key = ec.generate_private_key(ec.SECP256R1())
            pem = key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
            tmp = directory / f".{stem}.key.{uuid.uuid4().hex}"
            _write_new(tmp, pem, 0o600)
            try:
                os.link(tmp, key_path)
            except FileExistsError:
                pass  # another process won the race; use its key
            finally:
                tmp.unlink(missing_ok=True)
        if not cert_path.exists():
            key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
            tmp = directory / f".{stem}.crt.{uuid.uuid4().hex}"
            _write_new(tmp, _build_cert(key, f"labelmaker-{stem}"), 0o644)
            try:
                os.link(tmp, cert_path)
            except FileExistsError:
                pass
            finally:
                tmp.unlink(missing_ok=True)
    return key_path, cert_path


def write_pinned(path: Path, pem: str) -> str:
    """Validate and atomically store a peer certificate; returns its
    fingerprint."""
    der = cert_pem_to_der(pem)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.parent / f".{path.name}.{uuid.uuid4().hex}"
    _write_new(tmp, pem.strip().encode("ascii") + b"\n", 0o644)
    os.replace(tmp, path)
    return fingerprint(der)
