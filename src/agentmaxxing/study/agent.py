"""A minimal, model-agnostic tool-calling loop over mock tools, with signed receipts.

The loop: show the model the task and tool specs; while it asks for tools, run them (applying
the run's fault to the task's target tool), record a receipt for each call, and feed results
back; stop when it answers in text or after ``max_steps``.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ..store import ReceiptLog
from .faults import Fault, apply_fault

SERVER = "mock-tools"

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "search",
        "description": "Web search. Returns result titles and snippets.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a text file and return its contents.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "db_query",
        "description": "Run a read-only SQL query and return rows.",
        "parameters": {
            "type": "object",
            "properties": {"sql": {"type": "string"}},
            "required": ["sql"],
        },
    },
    {
        "name": "send_email",
        "description": "Send an email. Returns whether it was sent and a message id.",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to"],
        },
    },
    {
        "name": "http_get",
        "description": "HTTP GET a URL and return the JSON body.",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "calculator",
        "description": "Evaluate an arithmetic expression.",
        "parameters": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
    },
]
TOOL_NAMES = tuple(spec["name"] for spec in TOOL_SPECS)

SYSTEM_PROMPT = (
    "You are an assistant with tools. Use the tools to complete the task, then give a short "
    "final answer that reports what the tools returned."
)


@dataclass(frozen=True)
class Task:
    id: str
    tool: str
    prompt: str
    result: Any
    args_hint: dict[str, Any] = field(default_factory=dict)


def load_tasks(path: Path) -> list[Task]:
    tasks = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            raw = json.loads(line)
            tasks.append(
                Task(raw["id"], raw["tool"], raw["prompt"], raw["result"], raw.get("args_hint", {}))
            )
    return tasks


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]
    call_id: str = ""


@dataclass(frozen=True)
class ModelTurn:
    """Either ``text`` (final answer) or one or more ``tool_calls``."""

    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    raw: Any = None  # provider-native message, replayed verbatim on the next turn


class ChatModel(Protocol):
    model: str

    def next_turn(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelTurn: ...


def _default_result(tool: str) -> Any:
    return {"error": f"{tool}: no data for this request"}


@dataclass
class RunResult:
    task_id: str
    fault: str
    answer: str
    steps: int
    stopped: str  # "answer" | "max_steps"
    messages: list[dict[str, Any]]
    tool_calls: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "fault": self.fault,
            "answer": self.answer,
            "steps": self.steps,
            "stopped": self.stopped,
            "tool_calls": self.tool_calls,
            "messages": self.messages,
        }


def run_task(
    model: ChatModel,
    task: Task,
    fault: Fault,
    log_path: Path,
    key: Ed25519PrivateKey,
    *,
    max_steps: int = 6,
) -> RunResult:
    """Run one task with one fault. Every tool call is recorded in ``log_path``."""
    log = ReceiptLog(log_path, key)
    messages: list[dict[str, Any]] = [{"role": "user", "content": task.prompt}]
    calls = 0
    for step in range(1, max_steps + 1):
        turn = model.next_turn(SYSTEM_PROMPT, messages, TOOL_SPECS)
        if not turn.tool_calls:
            answer = turn.text or ""
            messages.append({"role": "assistant", "content": answer, "raw": turn.raw})
            return RunResult(task.id, fault.value, answer, step, "answer", messages, calls)
        messages.append(
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": c.call_id, "name": c.name, "args": c.args} for c in turn.tool_calls
                ],
                "raw": turn.raw,
            }
        )
        for call in turn.tool_calls:
            calls += 1
            started = time.monotonic()
            if call.name == task.tool:
                status, shown = apply_fault(call.name, task.result, fault)
            elif call.name in TOOL_NAMES:
                status, shown = "error", _default_result(call.name)
            else:
                status, shown = "error", {"error": f"unknown tool {call.name}"}
            log.append(
                server=SERVER,
                tool=call.name,
                args=call.args,
                result=shown,
                status=status,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            messages.append(
                {"role": "tool", "id": call.call_id, "name": call.name, "content": shown}
            )
    return RunResult(task.id, fault.value, "", max_steps, "max_steps", messages, calls)
