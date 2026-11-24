"""Append-only JSONL receipt store."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .receipts import GENESIS_HASH, Receipt, Status, make_receipt


class ReceiptLog:
    """Appends signed, hash-chained receipts to a JSONL file.

    Resumes the chain from the last line of an existing file. Thread-safe within one process;
    do not write to the same file from several processes.
    """

    def __init__(
        self,
        path: Path,
        private_key: Ed25519PrivateKey,
        *,
        max_stored_bytes: int | None = None,
    ) -> None:
        self.path = path
        self._max_stored_bytes = max_stored_bytes
        self._key = private_key
        self._lock = threading.Lock()
        self._prev_hash = self._last_hash()

    def _last_hash(self) -> str:
        if not self.path.exists():
            return GENESIS_HASH
        last = ""
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last = line
        if not last:
            return GENESIS_HASH
        try:
            value = json.loads(last)["hash"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(
                f"{self.path}: last line is not a valid receipt; refusing to append"
            ) from exc
        if not isinstance(value, str):
            raise ValueError(f"{self.path}: last receipt has a non-string hash")
        return value

    @property
    def head(self) -> str:
        return self._prev_hash

    def append(
        self,
        *,
        server: str,
        tool: str,
        args: Any,
        result: Any,
        status: Status,
        duration_ms: int,
    ) -> Receipt:
        with self._lock:
            receipt = make_receipt(
                private_key=self._key,
                server=server,
                tool=tool,
                args=args,
                result=result,
                status=status,
                duration_ms=duration_ms,
                prev_hash=self._prev_hash,
                max_stored_bytes=self._max_stored_bytes,
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(receipt.to_line() + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            self._prev_hash = receipt.data["hash"]
            return receipt
