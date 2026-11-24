"""Integration tests: a real ``agentmaxxing proxy`` process in front of real upstream processes."""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from agentmaxxing.keys import generate, load_public
from agentmaxxing.receipts import canonical_json, sha256_hex
from agentmaxxing.verify import verify_log

SUPPORT = Path(__file__).parent / "support"
MOCK = [sys.executable, str(SUPPORT / "mock_server.py")]
RAW = [sys.executable, str(SUPPORT / "raw_upstream.py")]


class Session:
    """Speaks line-delimited JSON-RPC to the proxy and collects what comes back."""

    def __init__(self, tmp: Path, upstream: list[str]) -> None:
        priv, pub = generate(tmp / "k")
        self.pub = pub
        self.log_path = tmp / "log.jsonl"
        self.proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "agentmaxxing.cli",
                "proxy",
                "--key",
                str(priv),
                "--log",
                str(self.log_path),
                "--server-name",
                "mock",
                "--",
                *upstream,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.raw_lines: list[bytes] = []
        self.by_id: dict[str, dict[str, Any]] = {}
        self.stderr = b""
        self._cond = threading.Condition()
        self._t = threading.Thread(target=self._read, daemon=True)
        self._te = threading.Thread(target=self._read_err, daemon=True)
        self._t.start()
        self._te.start()

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for line in iter(self.proc.stdout.readline, b""):
            with self._cond:
                self.raw_lines.append(line)
                try:
                    msg = json.loads(line)
                except ValueError:
                    msg = None
                if isinstance(msg, dict) and "id" in msg:
                    self.by_id[json.dumps(msg["id"])] = msg
                self._cond.notify_all()

    def _read_err(self) -> None:
        assert self.proc.stderr is not None
        self.stderr = self.proc.stderr.read()

    def send_raw(self, line: bytes) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(line if line.endswith(b"\n") else line + b"\n")
        self.proc.stdin.flush()

    def send(self, msg: dict[str, Any]) -> None:
        self.send_raw(json.dumps(msg).encode())

    def wait_for(self, request_id: Any, timeout: float = 30) -> dict[str, Any]:
        key = json.dumps(request_id)
        deadline = time.monotonic() + timeout
        with self._cond:
            while key not in self.by_id:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise AssertionError(f"no reply for id {request_id!r}")
                self._cond.wait(left)
            return self.by_id[key]

    def initialize(self) -> None:
        self.send(
            {
                "jsonrpc": "2.0",
                "id": "init",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0"},
                },
            }
        )
        self.wait_for("init")
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call(self, request_id: Any, tool: str, **arguments: Any) -> None:
        self.send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            }
        )

    def close(self, timeout: float = 60) -> int:
        assert self.proc.stdin is not None
        with contextlib.suppress(OSError):
            self.proc.stdin.close()
        code = self.proc.wait(timeout=timeout)
        self._t.join(timeout=5)
        self._te.join(timeout=5)
        return code

    def receipts(self) -> list[dict[str, Any]]:
        if not self.log_path.exists():
            return []
        lines = self.log_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(ln) for ln in lines if ln.strip()]

    def assert_log_verifies(self) -> None:
        result = verify_log(self.log_path, load_public(self.pub))
        assert result.ok, str(result)


SessionFactory = Callable[..., Session]


@pytest.fixture
def session(tmp_path: Path) -> Iterator[SessionFactory]:
    made: list[Session] = []

    def make(upstream: list[str] | None = None) -> Session:
        s = Session(tmp_path, upstream or MOCK)
        made.append(s)
        return s

    yield make
    for s in made:
        if s.proc.poll() is None:
            s.proc.kill()
            s.proc.wait()


def test_ok_call_records_one_verifiable_receipt(session: SessionFactory) -> None:
    s = session()
    s.initialize()
    s.call(1, "add", a=2, b=3)
    reply = s.wait_for(1)
    assert reply["result"]["isError"] is False
    assert s.close() == 0
    (r,) = s.receipts()
    assert (r["server"], r["tool"], r["status"]) == ("mock", "add", "ok")
    assert r["args"] == {"a": 2, "b": 3}
    assert r["args_sha256"] == sha256_hex(canonical_json({"a": 2, "b": 3}))
    assert r["result_sha256"] == sha256_hex(canonical_json(reply["result"]))
    s.assert_log_verifies()


def test_tool_error_is_recorded_as_error(session: SessionFactory) -> None:
    s = session()
    s.initialize()
    s.call(1, "fail")
    assert s.wait_for(1)["result"]["isError"] is True
    s.call(2, "no_such_tool")
    s.wait_for(2)
    s.close()
    r1, r2 = s.receipts()
    assert (r1["tool"], r1["status"]) == ("fail", "error")
    assert (r2["tool"], r2["status"]) == ("no_such_tool", "error")
    s.assert_log_verifies()


def test_other_traffic_passes_through_without_receipts(session: SessionFactory) -> None:
    s = session()
    s.initialize()
    s.send({"jsonrpc": "2.0", "id": "list", "method": "tools/list"})
    names = {t["name"] for t in s.wait_for("list")["result"]["tools"]}
    assert {"add", "slow", "fail", "big", "crash"} <= names
    s.send({"jsonrpc": "2.0", "id": "ping", "method": "ping"})
    s.wait_for("ping")
    s.close()
    assert s.receipts() == []


def test_concurrent_interleaved_ids_get_the_right_receipts(session: SessionFactory) -> None:
    s = session()
    s.initialize()
    s.call(10, "slow", seconds=1.0, label="A")
    s.call(11, "slow", seconds=0.3, label="B")
    s.call("11", "add", a=1, b=1)  # string "11" must not collide with integer 11
    s.call(12, "add", a=4, b=5)
    for rid in (10, 11, "11", 12):
        s.wait_for(rid)
    s.close()
    rs = s.receipts()
    assert len(rs) == 4
    assert all(r["status"] == "ok" for r in rs)
    by_args = {canonical_json(r["args"]): r for r in rs}
    a = by_args[canonical_json({"seconds": 1.0, "label": "A"})]
    b = by_args[canonical_json({"seconds": 0.3, "label": "B"})]
    assert "A" in json.dumps(a["result"]) and "B" not in json.dumps(a["result"])
    assert "B" in json.dumps(b["result"])
    assert b["duration_ms"] < a["duration_ms"]
    assert rs[-1] is a or rs[-1]["args"] == a["args"]  # the slowest call finishes last
    s.assert_log_verifies()


def test_cancelled_notification_closes_the_call(session: SessionFactory) -> None:
    s = session()
    s.initialize()
    s.call(1, "slow", seconds=3, label="never")
    time.sleep(0.5)
    s.send(
        {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": 1, "reason": "user pressed stop"},
        }
    )
    s.call(2, "slow", seconds=3, label="never2")
    time.sleep(0.3)
    s.send(
        {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": 2, "reason": "request timed out"},
        }
    )
    s.close()
    rs = s.receipts()
    assert len(rs) == 2  # a late upstream reply must not add a second receipt
    r1, r2 = rs
    assert r1["status"] == "cancelled" and r1["tool"] == "slow"
    assert r2["status"] == "timeout"
    s.assert_log_verifies()


def test_upstream_crash_closes_open_calls_and_log_verifies(session: SessionFactory) -> None:
    s = session()
    s.initialize()
    s.call(1, "add", a=1, b=2)
    s.wait_for(1)
    s.call(2, "crash")
    s.call(3, "slow", seconds=5, label="lost")
    code = s.close()
    assert code == 3  # the upstream's exit code is surfaced
    rs = s.receipts()
    assert {r["tool"] for r in rs} == {"add", "crash", "slow"}
    assert [r["status"] for r in rs if r["tool"] == "add"] == ["ok"]
    lost = [r for r in rs if r["tool"] in ("crash", "slow")]
    assert all(r["status"] == "error" for r in lost)
    assert all("upstream exited" in json.dumps(r["result"]) for r in lost)
    s.assert_log_verifies()


def test_client_disconnect_with_call_in_flight(session: SessionFactory) -> None:
    s = session()
    s.initialize()
    s.call(1, "slow", seconds=1, label="x")
    s.close()  # stdin closed immediately
    (r,) = s.receipts()  # exactly one receipt, however the upstream reacts
    # The SDK server answers in-flight calls with a JSON-RPC "Connection closed" error when its
    # stdin closes; the proxy records what the upstream really said. Other upstreams may finish
    # the call or say nothing (then the proxy writes "cancelled").
    assert r["tool"] == "slow" and r["status"] in ("ok", "cancelled", "error")
    s.assert_log_verifies()


def test_malformed_json_from_client_is_forwarded_and_ignored(session: SessionFactory) -> None:
    s = session()
    s.initialize()
    s.send_raw(b"{ this is not json")
    s.send_raw(b"\xff\xfe\x00 garbage bytes")
    s.call(1, "add", a=1, b=1)
    assert s.wait_for(1)["result"]["isError"] is False
    s.close()
    assert b"malformed JSON from client" in s.stderr
    assert [r["tool"] for r in s.receipts()] == ["add"]
    s.assert_log_verifies()


def test_malformed_json_from_upstream_and_byte_exact_passthrough(
    session: SessionFactory,
) -> None:
    s = session(RAW)
    s.call(7, "anything", x=1)
    s.wait_for(7)
    s.close()
    assert b"this is { not json\n" in s.raw_lines  # garbage reaches the client untouched
    expected = (
        b'{ "jsonrpc" : "2.0" ,  "id" : 7 , "result" : { "content" : [ ] , '
        b'"isError" : false , "marker" : "\xc3\xa9" } }\n'
    )
    assert expected in s.raw_lines  # a valid line is byte-for-byte identical
    assert b"malformed JSON from upstream" in s.stderr
    (r,) = s.receipts()
    assert r["tool"] == "anything" and r["status"] == "ok"
    s.assert_log_verifies()


def test_large_payload_is_forwarded_whole_and_hashed_exactly(session: SessionFactory) -> None:
    size = 3_000_000
    s = session()
    s.initialize()
    s.call(1, "big", size=size)
    reply = s.wait_for(1, timeout=60)
    assert len(reply["result"]["content"][0]["text"]) == size
    s.close()
    (r,) = s.receipts()
    assert r["result"]["_truncated"] is True  # the stored form is bounded...
    assert len(json.dumps(r["result"])) < 5000
    assert r["result_sha256"] == sha256_hex(canonical_json(reply["result"]))  # ...the hash is exact
    s.assert_log_verifies()


def test_secret_looking_args_are_not_stored(session: SessionFactory) -> None:
    s = session()
    s.initialize()
    s.call(1, "secret_echo", api_key="sk-live-123456")
    s.wait_for(1)
    s.close()
    text = s.log_path.read_text(encoding="utf-8")
    assert "sk-live-123456" not in text
    s.assert_log_verifies()


def test_missing_upstream_command_fails_cleanly(tmp_path: Path) -> None:
    priv, _ = generate(tmp_path / "k")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "agentmaxxing.cli",
            "proxy",
            "--key",
            str(priv),
            "--log",
            str(tmp_path / "l.jsonl"),
            "--",
            "definitely-not-a-real-command-xyz",
        ],
        capture_output=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    )
    assert proc.returncode == 127
    assert b"cannot start upstream" in proc.stderr
