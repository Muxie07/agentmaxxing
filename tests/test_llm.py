"""Gemini client: request shape, retries, schema fallback, key handling. No network."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from agentmaxxing.llm import GeminiClient, GeminiError, OllamaClient, make_client, read_env_key

KEY = "test-key-abc123-not-real"


def reply(text: str, version: str = "gemini-test-001") -> dict[str, Any]:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}], "modelVersion": version}


class FakeOpener:
    """Returns queued replies; an int queues an HTTP error with that status."""

    def __init__(self, queue: list[Any]) -> None:
        self.queue = queue
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> Any:
        self.requests.append(request)
        item = self.queue.pop(0)
        if isinstance(item, tuple):
            status, body = item
            headers = Message()
            raise urllib.error.HTTPError(
                request.full_url, status, "err", headers, io.BytesIO(body.encode())
            )
        return io.BytesIO(json.dumps(item).encode())


def client(opener: FakeOpener, **kw: Any) -> tuple[GeminiClient, list[float]]:
    sleeps: list[float] = []
    c = GeminiClient("gemini-x", api_key=KEY, opener=opener, sleep=sleeps.append, **kw)
    return c, sleeps


def test_request_shape_and_key_in_header_not_url() -> None:
    opener = FakeOpener([reply('{"claims": []}')])
    c, _ = client(opener, seed=7)
    out = c.complete_json("SYS", "USER", {"type": "object"})
    assert out == '{"claims": []}'
    req = opener.requests[0]
    assert KEY not in req.full_url
    assert req.full_url.endswith("/models/gemini-x:generateContent")
    assert req.get_header("X-goog-api-key") == KEY
    body = json.loads(req.data or b"{}")
    assert body["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert body["generationConfig"]["responseJsonSchema"] == {"type": "object"}
    assert body["generationConfig"]["temperature"] == 0.0
    assert body["generationConfig"]["seed"] == 7
    assert c.model_version == "gemini-test-001"


def test_retries_429_and_503_with_backoff() -> None:
    opener = FakeOpener([(429, "slow down"), (503, "busy"), reply("{}")])
    c, sleeps = client(opener)
    assert c.complete_json("s", "u", {}) == "{}"
    assert sleeps == [2.0, 4.0]
    assert c.retries == 2


def test_gives_up_after_max_retries() -> None:
    opener = FakeOpener([(429, "x")] * 3)
    c, _ = client(opener, max_retries=2)
    with pytest.raises(GeminiError, match="HTTP 429"):
        c.complete_json("s", "u", {})


def test_schema_rejected_falls_back_to_json_mode_once() -> None:
    opener = FakeOpener([(400, "bad schema"), reply("{}")])
    c, _ = client(opener)
    assert c.complete_json("s", "u", {"type": "object"}) == "{}"
    second = json.loads(opener.requests[1].data or b"{}")
    assert "responseJsonSchema" not in second["generationConfig"]
    assert c.schema_fallbacks == 1


def test_key_scrubbed_from_errors() -> None:
    opener = FakeOpener([(403, f"API key {KEY} not valid"), (403, f"API key {KEY} not valid")])
    c, _ = client(opener)
    with pytest.raises(GeminiError) as info:
        c.complete_json("s", "u", {})
    assert KEY not in str(info.value)
    assert "[REDACTED]" in str(info.value)


def test_blocked_reply_is_an_error() -> None:
    opener = FakeOpener([{"candidates": [{"finishReason": "SAFETY"}]}])
    c, _ = client(opener)
    with pytest.raises(GeminiError, match="SAFETY"):
        c.complete_json("s", "u", {})


def test_read_env_key_from_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text('# comment\nGROQ_API_KEY=\nGEMINI_API_KEY="from-file"\n', encoding="utf-8")
    assert read_env_key("GEMINI_API_KEY", env) == "from-file"
    assert read_env_key("GROQ_API_KEY", env) is None
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    assert read_env_key("GEMINI_API_KEY", env) == "from-env"


def test_missing_key_is_a_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(GeminiError, match="GEMINI_API_KEY is not set"):
        GeminiClient("gemini-x", env_file=tmp_path / "none")


def test_make_client_routes_by_model_name() -> None:
    assert isinstance(make_client("deepseek-r1:latest", host="http://x"), OllamaClient)
    g = make_client("gemini-2.5-flash", api_key=KEY, host="ignored")
    assert isinstance(g, GeminiClient)


def test_evaluation_aborted_propagates_instead_of_counting_as_failure() -> None:
    from agentmaxxing.extractor_eval import EvaluationAborted, evaluate

    example = {"id": "e1", "tools": ["search"], "answer": "x", "receipts": [], "claims": []}

    def extract(ex: dict[str, Any]) -> list[Any]:
        raise EvaluationAborted("setup is broken")

    with pytest.raises(EvaluationAborted):
        evaluate([example], extract)
