"""Verify a receipt log: schema, hash, chain linkage and Ed25519 signature, per line."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .receipts import ALL_FIELDS, GENESIS_HASH, STATUSES, compute_hash

_HEX64 = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    receipts: int
    bad_line: int | None = None  # 1-based line number of the first problem
    reason: str = ""
    head: str = GENESIS_HASH  # hash of the last good receipt

    def __str__(self) -> str:
        if self.ok:
            return f"OK: {self.receipts} receipts verified (head {self.head})"
        return f"INVALID at line {self.bad_line}: {self.reason}"


def _is_hex64(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX64


def _check_schema(rec: Any) -> str | None:
    if not isinstance(rec, dict):
        return "line is not a JSON object"
    missing = ALL_FIELDS - rec.keys()
    if missing:
        return f"missing fields: {', '.join(sorted(missing))}"
    extra = rec.keys() - ALL_FIELDS
    if extra:
        return f"unexpected fields: {', '.join(sorted(extra))}"
    for name in ("id", "timestamp", "server", "tool"):
        if not isinstance(rec[name], str):
            return f"{name} must be a string"
    if rec["status"] not in STATUSES:
        return f"invalid status {rec['status']!r}"
    duration = rec["duration_ms"]
    if isinstance(duration, bool) or not isinstance(duration, int) or duration < 0:
        return "duration_ms must be a non-negative integer"
    for name in ("args_sha256", "result_sha256", "prev_hash", "hash"):
        if not _is_hex64(rec[name]):
            return f"{name} must be 64 lowercase hex characters"
    if not isinstance(rec["signature"], str):
        return "signature must be a string"
    return None


def verify_log(
    path: Path,
    public_key: Ed25519PublicKey,
    *,
    expect_head: str | None = None,
) -> VerifyResult:
    """Return the first problem found, or ok.

    Detects: edited fields, deleted/reordered/inserted lines, wrong key, a file cut mid-line.
    Cannot detect on its own: removal of the *tail* of the log at a line boundary. Pass
    ``expect_head`` (the last known-good hash) to catch that.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return VerifyResult(False, 0, 0, f"cannot read log: {exc}")

    if raw and not raw.endswith(b"\n"):
        # A complete log always ends with a newline, so this is a truncated final line.
        complete, _, _partial = raw.rpartition(b"\n")
        good = _verify_lines(complete.split(b"\n") if complete else [], public_key)
        if not good.ok:
            return good
        return VerifyResult(
            False,
            good.receipts,
            good.receipts + 1,
            "file is truncated (last line is incomplete)",
            good.head,
        )

    lines = raw.split(b"\n")[:-1] if raw else []
    result = _verify_lines(lines, public_key)
    if not result.ok:
        return result
    if expect_head is not None and result.head != expect_head:
        return VerifyResult(
            False,
            result.receipts,
            result.receipts + 1,
            f"log head {result.head} does not match expected head {expect_head} "
            "(receipts were removed from the end, or this is a different log)",
            result.head,
        )
    return result


def _verify_lines(lines: list[bytes], public_key: Ed25519PublicKey) -> VerifyResult:
    prev = GENESIS_HASH
    count = 0
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            return VerifyResult(False, count, number, "blank line", prev)
        try:
            rec = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return VerifyResult(False, count, number, "line is not valid JSON", prev)
        problem = _check_schema(rec)
        if problem:
            return VerifyResult(False, count, number, problem, prev)
        if rec["prev_hash"] != prev:
            return VerifyResult(
                False,
                count,
                number,
                "prev_hash does not match the previous receipt "
                "(a line was deleted, inserted or reordered)",
                prev,
            )
        if compute_hash(rec) != rec["hash"]:
            return VerifyResult(False, count, number, "hash mismatch (a field was edited)", prev)
        try:
            public_key.verify(bytes.fromhex(rec["signature"]), rec["hash"].encode("ascii"))
        except (InvalidSignature, ValueError):
            return VerifyResult(
                False, count, number, "signature invalid (wrong key or forged receipt)", prev
            )
        prev = rec["hash"]
        count += 1
    return VerifyResult(True, count, None, "", prev)
