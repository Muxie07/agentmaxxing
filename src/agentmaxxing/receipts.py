"""Receipt format: canonical JSON, redaction, hash chaining and Ed25519 signing."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

GENESIS_HASH = "0" * 64
Status = Literal["ok", "error", "timeout", "cancelled"]
STATUSES: frozenset[str] = frozenset({"ok", "error", "timeout", "cancelled"})

# Fields covered by `hash`. `hash` itself and `signature` are excluded.
BODY_FIELDS: tuple[str, ...] = (
    "id",
    "timestamp",
    "server",
    "tool",
    "args",
    "result",
    "args_sha256",
    "result_sha256",
    "status",
    "duration_ms",
    "prev_hash",
)
ALL_FIELDS: frozenset[str] = frozenset((*BODY_FIELDS, "hash", "signature"))

_SECRET_KEY = re.compile(
    r"(secret|token|passw(or)?d|passwd|api[_-]?key|apikey|authorization|credential|"
    r"private[_-]?key|bearer|cookie|session[_-]?id)",
    re.IGNORECASE,
)
REDACTED = "[REDACTED]"


def canonical_json(value: Any) -> str:
    """Sorted keys, no spaces, non-ASCII kept as UTF-8. Deterministic across runs."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def redact(value: Any) -> Any:
    """Recursively replace values stored under secret-looking keys.

    Only key names are inspected. A secret sitting in a free-text value is NOT detected.
    """
    if isinstance(value, dict):
        return {
            k: (REDACTED if isinstance(k, str) and _SECRET_KEY.search(k) else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def bound(value: Any, max_bytes: int | None) -> Any:
    """Replace an oversized value with a small marker. The receipt's SHA-256 fields still
    cover the full raw value, so the original can be proven against the receipt."""
    if max_bytes is None:
        return value
    text = canonical_json(value)
    size = len(text.encode("utf-8"))
    if size <= max_bytes:
        return value
    return {"_truncated": True, "original_bytes": size, "preview": text[:1024]}


def compute_hash(body: dict[str, Any]) -> str:
    return sha256_hex(canonical_json({k: body[k] for k in BODY_FIELDS}))


@dataclass(frozen=True)
class Receipt:
    data: dict[str, Any]

    def to_line(self) -> str:
        return canonical_json(self.data)


def make_receipt(
    *,
    private_key: Ed25519PrivateKey,
    server: str,
    tool: str,
    args: Any,
    result: Any,
    status: Status,
    duration_ms: int,
    prev_hash: str,
    receipt_id: str | None = None,
    timestamp: str | None = None,
    max_stored_bytes: int | None = None,
) -> Receipt:
    """Build, hash and sign one receipt.

    ``args_sha256``/``result_sha256`` are computed over the RAW values, so a holder of the
    original data can prove it matches; the stored ``args``/``result`` are redacted copies.
    """
    if status not in STATUSES:
        raise ValueError(f"invalid status {status!r}")
    body: dict[str, Any] = {
        "id": receipt_id or uuid.uuid4().hex,
        "timestamp": timestamp or datetime.now(UTC).isoformat(timespec="milliseconds"),
        "server": server,
        "tool": tool,
        "args": bound(redact(args), max_stored_bytes),
        "result": bound(redact(result), max_stored_bytes),
        "args_sha256": sha256_hex(canonical_json(args)),
        "result_sha256": sha256_hex(canonical_json(result)),
        "status": status,
        "duration_ms": int(duration_ms),
        "prev_hash": prev_hash,
    }
    digest = compute_hash(body)
    body["hash"] = digest
    body["signature"] = private_key.sign(digest.encode("ascii")).hex()
    return Receipt(body)
