"""MCP stdio proxy: wraps an upstream MCP server and writes one receipt per ``tools/call``.

MCP's stdio transport is newline-delimited JSON-RPC. The proxy forwards every line to the
other side byte-for-byte and only *observes* it, so protocol behaviour is unchanged:

* client -> upstream: a ``tools/call`` request is remembered by id; ``notifications/cancelled``
  closes the matching call with status ``cancelled`` (or ``timeout`` if the reason says so).
* upstream -> client: the response with a remembered id closes the call as ``ok`` or
  ``error`` (JSON-RPC error, or a result with ``isError: true``).
* If the upstream dies or the client disconnects, still-open calls are closed with a note.

Anything that is not valid JSON is forwarded untouched and counted; it never gets a receipt.
Diagnostics go to stderr only, because stdout carries the protocol.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, BinaryIO

from .receipts import Status
from .store import ReceiptLog

GRACE_SECONDS = 5.0
_TIMEOUT_WORDS = ("timed out", "timeout", "time out")


@dataclass
class _Pending:
    tool: str
    args: Any
    started: float


def _id_key(request_id: Any) -> str:
    # json.dumps keeps 1 and "1" distinct, as JSON-RPC requires.
    return json.dumps(request_id)


def _messages(parsed: Any) -> list[dict[str, Any]]:
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):  # JSON-RPC batch
        return [m for m in parsed if isinstance(m, dict)]
    return []


class Proxy:
    def __init__(
        self,
        command: list[str],
        log: ReceiptLog,
        *,
        server_name: str,
        client_in: BinaryIO,
        client_out: BinaryIO,
        client_err: BinaryIO,
    ) -> None:
        self.command = command
        self.log = log
        self.server_name = server_name
        self._client_in = client_in
        self._client_out = client_out
        self._client_err = client_err
        self._pending: dict[str, _Pending] = {}
        self._plock = threading.Lock()
        self._out_lock = threading.Lock()
        self._err_lock = threading.Lock()
        self._proc: subprocess.Popen[bytes] | None = None
        self._client_eof = False
        self._we_terminated = False
        self.malformed_from_client = 0
        self.malformed_from_upstream = 0

    # ---------- receipts ----------

    def _register(self, request_id: Any, params: Any) -> None:
        p = params if isinstance(params, dict) else {}
        tool = p.get("name")
        args = p.get("arguments", {})
        key = _id_key(request_id)
        with self._plock:
            previous = self._pending.get(key)
            self._pending[key] = _Pending(
                tool if isinstance(tool, str) else "<unknown>", args, time.monotonic()
            )
        if previous is not None:  # a client reused an in-flight id; don't lose the first call
            self._append(previous, "error", {"proxy_note": "request id was reused before reply"})

    def _finish(self, request_id: Any, status: Status, result: Any) -> None:
        with self._plock:
            pending = self._pending.pop(_id_key(request_id), None)
        if pending is not None:
            self._append(pending, status, result)

    def _append(self, pending: _Pending, status: Status, result: Any) -> None:
        self.log.append(
            server=self.server_name,
            tool=pending.tool,
            args=pending.args,
            result=result,
            status=status,
            duration_ms=int((time.monotonic() - pending.started) * 1000),
        )

    # ---------- observation ----------

    def _observe_client(self, line: bytes) -> None:
        try:
            parsed = json.loads(line)
        except (UnicodeDecodeError, ValueError):
            self.malformed_from_client += 1
            self._note("malformed JSON from client forwarded untouched")
            return
        for msg in _messages(parsed):
            method = msg.get("method")
            if method == "tools/call" and msg.get("id") is not None:
                self._register(msg["id"], msg.get("params"))
            elif method == "notifications/cancelled":
                params = msg.get("params")
                if isinstance(params, dict) and params.get("requestId") is not None:
                    reason = str(params.get("reason") or "")
                    timed_out = any(w in reason.lower() for w in _TIMEOUT_WORDS)
                    status: Status = "timeout" if timed_out else "cancelled"
                    self._finish(
                        params["requestId"],
                        status,
                        {"proxy_note": f"client sent notifications/cancelled: {reason}".strip()},
                    )

    def _observe_upstream(self, line: bytes) -> None:
        try:
            parsed = json.loads(line)
        except (UnicodeDecodeError, ValueError):
            self.malformed_from_upstream += 1
            self._note("malformed JSON from upstream forwarded untouched")
            return
        for msg in _messages(parsed):
            if "method" in msg or msg.get("id") is None:
                continue
            if "error" in msg:
                self._finish(msg["id"], "error", msg["error"])
            elif "result" in msg:
                result = msg["result"]
                failed = isinstance(result, dict) and result.get("isError") is True
                self._finish(msg["id"], "error" if failed else "ok", result)

    # ---------- plumbing ----------

    def _note(self, text: str) -> None:
        with self._err_lock:
            self._client_err.write(f"agentmaxxing proxy: {text}\n".encode())
            self._client_err.flush()

    def _send_client(self, line: bytes) -> None:
        try:
            with self._out_lock:
                self._client_out.write(line)
                self._client_out.flush()
        except (BrokenPipeError, ValueError, OSError):
            self._terminate()

    def _terminate(self) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            self._we_terminated = True
            proc.terminate()

    def _pump_client(self, proc: subprocess.Popen[bytes]) -> None:
        assert proc.stdin is not None
        try:
            for line in iter(self._client_in.readline, b""):
                if not line.endswith(b"\n"):
                    line += b"\n"
                self._observe_client(line)
                try:
                    proc.stdin.write(line)
                    proc.stdin.flush()
                except (BrokenPipeError, OSError, ValueError):
                    return  # upstream is gone; the main thread will clean up
            self._client_eof = True  # only when the client itself closed its end
        finally:
            with contextlib.suppress(BrokenPipeError, OSError, ValueError):
                proc.stdin.close()
        try:
            proc.wait(timeout=GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            self._terminate()

    def _pump_upstream(self, proc: subprocess.Popen[bytes]) -> None:
        assert proc.stdout is not None
        for line in iter(proc.stdout.readline, b""):
            if not line.endswith(b"\n"):
                line += b"\n"
            self._observe_upstream(line)
            self._send_client(line)

    def _pump_stderr(self, proc: subprocess.Popen[bytes]) -> None:
        assert proc.stderr is not None
        for line in iter(proc.stderr.readline, b""):
            with self._err_lock:
                self._client_err.write(line)
                self._client_err.flush()

    def run(self) -> int:
        exe = shutil.which(self.command[0]) or self.command[0]
        try:
            proc = subprocess.Popen(
                [exe, *self.command[1:]],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            self._note(f"cannot start upstream {self.command[0]!r}: {exc}")
            return 127
        self._proc = proc

        t_in = threading.Thread(target=self._pump_client, args=(proc,), daemon=True)
        t_out = threading.Thread(target=self._pump_upstream, args=(proc,), daemon=True)
        t_err = threading.Thread(target=self._pump_stderr, args=(proc,), daemon=True)
        for t in (t_in, t_out, t_err):
            t.start()

        t_out.join()  # upstream closed its stdout: it exited or is shutting down
        try:
            code = proc.wait(timeout=GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            self._terminate()
            code = proc.wait()
        t_err.join(timeout=2)

        with self._plock:
            leftover = list(self._pending)
        for key in leftover:
            # A non-zero exit we did not cause is an upstream failure even if the client also
            # hung up; only a clean shutdown after client EOF counts as cancellation.
            if self._client_eof and (code == 0 or self._we_terminated):
                note = "client disconnected before the upstream replied"
                status: Status = "cancelled"
            else:
                note = f"upstream exited (code {code}) before replying"
                status = "error"
            self._finish(json.loads(key), status, {"proxy_note": note})

        with contextlib.suppress(OSError, ValueError):
            self._client_out.close()
        return 0 if self._we_terminated else code
