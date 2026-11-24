"""Gemini function-calling adapter for the study's agent loop.

Model turns are replayed with their original parts (``raw``), which newer Gemini models need
for thought signatures. Uses the same key handling and retries as ``GeminiClient``.
"""

from __future__ import annotations

import copy
from typing import Any

from ..llm import GeminiClient, GeminiError
from .agent import ModelTurn, ToolCall


def _declaration(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": spec["name"],
        "description": spec["description"],
        "parametersJsonSchema": spec["parameters"],
    }


def _response_object(content: Any) -> dict[str, Any]:
    return content if isinstance(content, dict) else {"result": content}


def to_contents(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contents: list[dict[str, Any]] = []
    pending_responses: list[dict[str, Any]] = []
    for m in messages:
        if m["role"] == "tool":
            pending_responses.append(
                {
                    "functionResponse": {
                        "name": m["name"],
                        "response": _response_object(m["content"]),
                        **({"id": m["id"]} if m.get("id") else {}),
                    }
                }
            )
            continue
        if pending_responses:
            contents.append({"role": "user", "parts": pending_responses})
            pending_responses = []
        if m["role"] == "user":
            contents.append({"role": "user", "parts": [{"text": m["content"]}]})
        elif m.get("raw") is not None:
            contents.append(copy.deepcopy(m["raw"]))
        elif m.get("tool_calls"):
            contents.append(
                {
                    "role": "model",
                    "parts": [
                        {"functionCall": {"name": c["name"], "args": c["args"]}}
                        for c in m["tool_calls"]
                    ],
                }
            )
        else:
            contents.append({"role": "model", "parts": [{"text": m.get("content", "")}]})
    if pending_responses:
        contents.append({"role": "user", "parts": pending_responses})
    return contents


class GeminiChat:
    def __init__(self, client: GeminiClient) -> None:
        self.client = client
        self.model = client.model

    def next_turn(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelTurn:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": to_contents(messages),
            "tools": [{"functionDeclarations": [_declaration(t) for t in tools]}],
            "generationConfig": {
                "temperature": self.client.temperature,
                "seed": self.client.seed,
            },
        }
        data = self.client._post(body)
        version = data.get("modelVersion")
        if isinstance(version, str):
            self.client.model_version = version
        try:
            content = data["candidates"][0]["content"]
            parts = content["parts"]
        except (KeyError, IndexError, TypeError):
            raise GeminiError("Gemini returned no content") from None
        calls = tuple(
            ToolCall(
                p["functionCall"]["name"],
                dict(p["functionCall"].get("args") or {}),
                str(p["functionCall"].get("id", "")),
            )
            for p in parts
            if isinstance(p, dict) and "functionCall" in p
        )
        text = "".join(
            p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought")
        )
        raw = {"role": content.get("role", "model"), "parts": parts}
        return ModelTurn(text=None if calls else text, tool_calls=calls, raw=raw)
