"""Minimal local-model client (Ollama). No keys, no cost, no third-party dependency."""

from __future__ import annotations

import json
import urllib.request
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
