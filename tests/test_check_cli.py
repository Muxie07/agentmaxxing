from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agentmaxxing import cli
from agentmaxxing.claims import Claim, Verdict, verify_claim
from agentmaxxing.keys import generate, load_private
from agentmaxxing.store import ReceiptLog


def make_log(tmp_path: Path) -> tuple[Path, Path]:
    priv, pub = generate(tmp_path / "k")
    log_path = tmp_path / "log.jsonl"
    log = ReceiptLog(log_path, load_private(priv))
    log.append(
        server="s",
        tool="read_file",
        args={"path": "a.txt"},
        result="alpha",
        status="ok",
        duration_ms=1,
    )
    log.append(
        server="s",
        tool="send_email",
        args={"to": "x@example.com"},
        result={"error": "bounced"},
        status="error",
        duration_ms=1,
    )
    return log_path, pub


def test_failure_claim_quoting_a_detail_is_checked_against_the_error_result() -> None:
    receipts = [
        {"id": "r", "tool": "http_get", "args": {}, "status": "error", "result": {"status": 404}}
    ]
    assert verify_claim(Claim("http_get", {}, "failure", ("404",)), receipts).verdict is (
        Verdict.VERIFIED
    )
    assert verify_claim(Claim("http_get", {}, "failure", ("500",)), receipts).verdict is (
        Verdict.RESULT_MISREPORTED
    )


def test_check_flags_a_failed_call_reported_as_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log_path, pub = make_log(tmp_path)
    transcript = [
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "1", "name": "read_file", "input": {"path": "a.txt"}},
                {
                    "type": "tool_use",
                    "id": "2",
                    "name": "send_email",
                    "input": {"to": "x@example.com"},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "1", "content": "alpha"},
                {"type": "tool_result", "tool_use_id": "2", "content": "sent"},
            ],
        },
    ]
    t = tmp_path / "t.json"
    t.write_text(json.dumps(transcript), encoding="utf-8")
    code = cli.main(["check", "--log", str(log_path), "--pubkey", str(pub), "--transcript", str(t)])
    out = capsys.readouterr().out
    assert code == 1
    assert "FAILED_REPORTED_AS_SUCCESS" in out and "send_email" in out
    assert "VERIFIED" in out


def test_check_exits_zero_when_everything_is_verified(tmp_path: Path) -> None:
    log_path, pub = make_log(tmp_path)
    transcript = [
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "1", "name": "read_file", "input": {"path": "a.txt"}}
            ],
        }
    ]
    t = tmp_path / "t.json"
    t.write_text(json.dumps(transcript), encoding="utf-8")
    argv = ["check", "--log", str(log_path), "--pubkey", str(pub), "--transcript", str(t)]
    assert cli.main(argv) == 0


def test_check_refuses_a_tampered_log(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log_path, pub = make_log(tmp_path)
    log_path.write_text(log_path.read_text(encoding="utf-8").replace("alpha", "bravo"), "utf-8")
    t = tmp_path / "t.json"
    t.write_text("[]", encoding="utf-8")
    code = cli.main(["check", "--log", str(log_path), "--pubkey", str(pub), "--transcript", str(t)])
    assert code == 2
    assert "not trustworthy" in capsys.readouterr().err


def test_check_natural_language_path_uses_the_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    log_path, pub = make_log(tmp_path)

    class Stub:
        def __init__(self, model: str, **_: Any) -> None:
            self.model = model

        def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> str:
            assert "read_file, send_email" in user
            return json.dumps(
                {"claims": [{"tool": "send_email", "args": {}, "outcome": "success", "facts": []}]}
            )

    monkeypatch.setattr(cli, "OllamaClient", Stub)
    answer = tmp_path / "answer.txt"
    answer.write_text("I emailed it.", encoding="utf-8")
    code = cli.main(
        ["check", "--log", str(log_path), "--pubkey", str(pub), "--answer", str(answer)]
    )
    assert code == 1
    assert "FAILED_REPORTED_AS_SUCCESS" in capsys.readouterr().out


def test_check_needs_an_input(tmp_path: Path) -> None:
    log_path, pub = make_log(tmp_path)
    assert cli.main(["check", "--log", str(log_path), "--pubkey", str(pub)]) == 2
