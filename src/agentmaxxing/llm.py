"""Minimal model clients: local Ollama and the Gemini API. Standard library only.

The Gemini key is read from the environment or a ``.env`` file. It is sent in a header,
never in the URL, and is scrubbed from every error message.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

DEFAULT_HOST = "http://localhost:11434"


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(
        self,
        model: str,
        *,
        host: str = DEFAULT_HOST,
        temperature: float = 0.0,
        seed: int = 0,
        timeout: float = 600.0,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.temperature = temperature
        self.seed = seed
        self.timeout = timeout

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> str:
        body = {
            "model": self.model,
            "stream": False,
            "think": False,
            "format": schema,
            "options": {"temperature": self.temperature, "seed": self.seed},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        request = urllib.request.Request(
            f"{self.host}/api/chat",
            json.dumps(body).encode(),
            {"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                data = json.load(response)
        except OSError as exc:
            raise OllamaError(f"cannot reach Ollama at {self.host}: {exc}") from exc
        content = data.get("message", {}).get("content")
        if not isinstance(content, str):
            raise OllamaError("unexpected Ollama reply (no message content)")
        return content


# ---------------------------------------------------------------- Gemini

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class GeminiError(RuntimeError):
    pass


def read_env_key(name: str, env_file: str | Path = ".env") -> str | None:
    """Return ``name`` from the environment, else from a simple KEY=value ``.env`` file."""
    value = os.environ.get(name)
    if value:
        return value.strip()
    path = Path(env_file)
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw = line.partition("=")
        if key.strip() == name:
            raw = raw.strip().strip('"').strip("'")
            return raw or None
    return None


class GeminiClient:
    """Calls ``models/{model}:generateContent`` with a JSON response schema.

    Retries 429 and 5xx with exponential backoff (honouring ``Retry-After``). If the API
    rejects the schema with a 400, it retries once with JSON mode only and records that in
    ``schema_fallbacks``.
    """

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        env_file: str | Path = ".env",
        temperature: float = 0.0,
        seed: int = 0,
        timeout: float = 120.0,
        max_retries: int = 6,
        base_delay: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        key = api_key or read_env_key("GEMINI_API_KEY", env_file)
        if not key:
            raise GeminiError("GEMINI_API_KEY is not set (environment or .env)")
        self.model = model
        self._key = key
        self.temperature = temperature
        self.seed = seed
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_delay = base_delay
        self._sleep = sleep
        self._open = opener
        self.model_version: str | None = None
        self.schema_fallbacks = 0
        self.retries = 0

    def _scrub(self, text: str) -> str:
        return text.replace(self._key, "[REDACTED]")

    def _body(self, system: str, user: str, schema: dict[str, Any] | None) -> dict[str, Any]:
        config: dict[str, Any] = {
            "temperature": self.temperature,
            "seed": self.seed,
            "responseMimeType": "application/json",
        }
        if schema is not None:
            config["responseJsonSchema"] = schema
        return {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": config,
        }

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{GEMINI_BASE}/models/{self.model}:generateContent",
            json.dumps(body).encode(),
            {"Content-Type": "application/json", "x-goog-api-key": self._key},
        )
        attempt = 0
        while True:
            try:
                with self._open(request, timeout=self.timeout) as response:
                    data = json.load(response)
                    if not isinstance(data, dict):
                        raise GeminiError("unexpected Gemini reply (not an object)")
                    return data
            except urllib.error.HTTPError as exc:
                detail = self._scrub(exc.read().decode("utf-8", "replace")[:500])
                if exc.code in RETRY_STATUSES and attempt < self.max_retries:
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    delay = (
                        float(retry_after)
                        if retry_after and retry_after.isdigit()
                        else self.base_delay * (2**attempt)
                    )
                    attempt += 1
                    self.retries += 1
                    self._sleep(min(delay, 120.0))
                    continue
                raise GeminiError(f"Gemini HTTP {exc.code}: {detail}") from None
            except OSError as exc:
                if attempt < self.max_retries:
                    attempt += 1
                    self.retries += 1
                    self._sleep(min(self.base_delay * (2**attempt), 120.0))
                    continue
                raise GeminiError(f"cannot reach Gemini: {self._scrub(str(exc))}") from None

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> str:
        try:
            data = self._post(self._body(system, user, schema))
        except GeminiError as exc:
            if "HTTP 400" not in str(exc):
                raise
            self.schema_fallbacks += 1
            data = self._post(self._body(system, user, None))
        version = data.get("modelVersion")
        if isinstance(version, str):
            self.model_version = version
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError):
            reason = None
            candidates = data.get("candidates")
            if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict):
                reason = candidates[0].get("finishReason")
            raise GeminiError(f"Gemini returned no content (finishReason={reason})") from None
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        if not text:
            raise GeminiError("Gemini returned an empty reply")
        return text


def make_client(model: str, **kwargs: Any) -> OllamaClient | GeminiClient:
    """``gemini-*`` / ``gemma-*`` models go to the Gemini API; anything else to Ollama."""
    if model.startswith(("gemini-", "gemma-")):
        gemini_keys = ("api_key", "env_file", "temperature", "seed", "timeout", "max_retries")
        return GeminiClient(model, **{k: v for k, v in kwargs.items() if k in gemini_keys})
    ollama_keys = ("host", "temperature", "seed", "timeout")
    return OllamaClient(model, **{k: v for k, v in kwargs.items() if k in ollama_keys})
