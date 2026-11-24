"""Ed25519 key generation and loading. Keys are stored as 64 hex characters (32 raw bytes)."""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


class KeyFileError(ValueError):
    """Raised when a key file is missing or malformed."""


def generate(out_prefix: Path, *, force: bool = False) -> tuple[Path, Path]:
    """Write ``<prefix>.key`` (private) and ``<prefix>.pub`` (public). Refuses to overwrite."""
    key_path = out_prefix.with_suffix(".key")
    pub_path = out_prefix.with_suffix(".pub")
    if not force and (key_path.exists() or pub_path.exists()):
        raise FileExistsError(f"{key_path} or {pub_path} already exists (use --force)")
    key_path.parent.mkdir(parents=True, exist_ok=True)
    private = Ed25519PrivateKey.generate()
    raw_private = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    raw_public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(raw_private.hex() + "\n")
    pub_path.write_text(raw_public.hex() + "\n")
    return key_path, pub_path


def _read_hex(path: Path) -> bytes:
    try:
        text = path.read_text().strip()
    except OSError as exc:
        raise KeyFileError(f"cannot read key file {path}: {exc}") from exc
    try:
        raw = bytes.fromhex(text)
    except ValueError as exc:
        raise KeyFileError(f"{path} is not a hex-encoded key") from exc
    if len(raw) != 32:
        raise KeyFileError(f"{path} must hold 32 bytes, got {len(raw)}")
    return raw


def load_private(path: Path) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(_read_hex(path))


def load_public(path: Path) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(_read_hex(path))
