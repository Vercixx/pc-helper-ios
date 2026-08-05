"""The server's long-term Ed25519 identity.

This key is the trust anchor the phone pins at pairing time. Losing it means every
paired device must be re-enrolled; leaking it lets an attacker impersonate the PC
to an already-paired phone. Hence the strict permission handling below.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .crypto.canonical import b64u_encode, fingerprint

KEY_FILENAME = "server_key.pem"


@dataclass(frozen=True, slots=True)
class ServerIdentity:
    private_key: Ed25519PrivateKey
    path: Path

    @property
    def public_raw(self) -> bytes:
        return self.private_key.public_key().public_bytes_raw()

    @property
    def public_b64(self) -> str:
        return b64u_encode(self.public_raw)

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.public_raw)

    @property
    def short_fingerprint(self) -> str:
        """First 8 characters, for terminal display and eyeball comparison."""
        return self.fingerprint[:8]

    def sign(self, message: bytes) -> bytes:
        return self.private_key.sign(message)


def load_or_create(state_dir: Path) -> ServerIdentity:
    """Load the server key, generating it on first run.

    Refuses to use a key file that is readable by group or other. Silently
    tightening the mode instead would hide the fact that the key may already have
    been exposed.
    """
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = state_dir / KEY_FILENAME

    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise PermissionError(
                f"{path} is mode {mode:04o}; it must not be readable by group or other. "
                f"Fix with: chmod 600 {path}"
            )
        data = path.read_bytes()
        key = serialization.load_pem_private_key(data, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError(f"{path} does not contain an Ed25519 private key")
        return ServerIdentity(private_key=key, path=path)

    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    _write_private(path, pem)
    return ServerIdentity(private_key=key, path=path)


def _write_private(path: Path, data: bytes) -> None:
    """Write 0600 atomically, and never leave a readable window.

    The temp file is created with O_EXCL and mode 0600 before any bytes are
    written, so the key is never briefly world-readable.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
