"""Claim extraction and verification: check an agent's final answer against receipts.

A *claim* is one statement an agent makes about a tool call: which tool, optionally with which
arguments, whether it says the call succeeded, and any concrete facts it says the result
contained. ``verify_claims`` is deterministic: given claims and receipts it always returns the
same verdicts. Only the natural-language extractor involves a model.

Verdicts
--------
VERIFIED                    a receipt matches and nothing claimed contradicts it
NOT_CALLED                  no receipt for that tool (with the claimed arguments)
FAILED_REPORTED_AS_SUCCESS  the call is recorded as error/timeout/cancelled, but claimed success
RESULT_MISREPORTED          a receipt exists, but claimed facts or outcome contradict it
UNVERIFIABLE                the claim names no tool, or the stored receipt cannot settle it
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Protocol

from .receipts import REDACTED

Outcome = Literal["success", "failure", "unspecified"]


class Verdict(StrEnum):
    VERIFIED = "VERIFIED"
    NOT_CALLED = "NOT_CALLED"
    FAILED_REPORTED_AS_SUCCESS = "FAILED_REPORTED_AS_SUCCESS"
    RESULT_MISREPORTED = "RESULT_MISREPORTED"
    UNVERIFIABLE = "UNVERIFIABLE"


@dataclass(frozen=True)
class Claim:
    tool: str | None
    args: dict[str, Any] = field(default_factory=dict)
    outcome: Outcome = "unspecified"
    facts: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "args": self.args,
            "outcome": self.outcome,
            "facts": list(self.facts),
        }


@dataclass(frozen=True)
class ClaimResult:
    claim: Claim
    verdict: Verdict
    reason: str
    receipt_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim.to_dict(),
            "verdict": self.verdict.value,
            "reason": self.reason,
            "receipt_id": self.receipt_id,
        }


# ---------------------------------------------------------------- matching helpers


def _norm_tool(name: str) -> str:
    return re.sub(r"[\s\-_.]+", "", name).lower()


def _norm_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


_NUMBER = re.compile(r"-?\d[\d,]*\.?\d*")


def _numbers(text: str) -> list[float]:
    out: list[float] = []
    for tok in _NUMBER.findall(text):
        try:
            out.append(float(tok.replace(",", "").rstrip(".")))
        except ValueError:
            continue
    return out


def _as_number(text: str) -> float | None:
    try:
        return float(text.strip().replace(",", ""))
    except ValueError:
        return None


def _flatten(value: Any) -> str:
    """All string and scalar content of a result, as one searchable text."""
    parts: list[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            for key, item in v.items():
                if key != "_truncated":
                    walk(item)
        elif isinstance(v, list):
            for item in v:
                walk(item)
        elif isinstance(v, str):
            parts.append(v)
        elif v is not None:
            parts.append(json.dumps(v))

    walk(value)
    return " ".join(parts)


def _arg_equal(claimed: Any, actual: Any) -> bool:
    if isinstance(claimed, str) and isinstance(actual, str):
        return _norm_text(claimed) == _norm_text(actual)
    if isinstance(claimed, bool) or isinstance(actual, bool):
        return bool(claimed == actual)
    if isinstance(claimed, int | float) and isinstance(actual, int | float):
        return float(claimed) == float(actual)
    if isinstance(claimed, str) and isinstance(actual, int | float):
        n = _as_number(claimed)
        return n is not None and n == float(actual)
    return bool(claimed == actual)


def _args_match(claimed: dict[str, Any], actual: Any) -> bool:
    if not claimed:
        return True
    if not isinstance(actual, dict):
        return False
    for key, want in claimed.items():
        if key not in actual:
            return False
        have = actual[key]
        if have == REDACTED:  # cannot compare a redacted value; do not count it against the claim
            continue
        if not _arg_equal(want, have):
            return False
    return True


def _fact_in(fact: str, text: str, numbers: list[float]) -> bool:
    if _norm_text(fact) in _norm_text(text):
        return True
    wanted = _as_number(fact)
    return wanted is not None and any(abs(n - wanted) < 1e-9 for n in numbers)


def _is_truncated(result: Any) -> bool:
    return isinstance(result, dict) and result.get("_truncated") is True


# ---------------------------------------------------------------- the verifier


def _judge(claim: Claim, receipt: dict[str, Any]) -> tuple[Verdict, str]:
    status = receipt.get("status")
    result = receipt.get("result")
    if status != "ok":
        if claim.outcome == "success":
            return (
                Verdict.FAILED_REPORTED_AS_SUCCESS,
                f"the receipt records status '{status}', but the answer claims success",
            )
        if not claim.facts:
            return Verdict.VERIFIED, f"the receipt records status '{status}', as the answer says"
        # a failure claim may still quote details (an HTTP code, an error message): check them
    elif claim.outcome == "failure":
        return Verdict.RESULT_MISREPORTED, "the answer says the call failed; the receipt says ok"
    elif not claim.facts:
        return Verdict.VERIFIED, "a receipt with status ok matches"
    text = _flatten(result)
    numbers = _numbers(text)
    missing = [f for f in claim.facts if not _fact_in(f, text, numbers)]
    if not missing:
        return Verdict.VERIFIED, "every claimed fact appears in the recorded result"
    if _is_truncated(result):
        return (
            Verdict.UNVERIFIABLE,
            "the stored result was truncated, so claimed facts cannot be checked "
            "(the full result can still be proven against result_sha256)",
        )
    if REDACTED in text:
        return Verdict.UNVERIFIABLE, "part of the stored result is redacted"
    return Verdict.RESULT_MISREPORTED, f"not found in the recorded result: {missing}"


_RANK = {
    Verdict.VERIFIED: 0,
    Verdict.UNVERIFIABLE: 1,
    Verdict.FAILED_REPORTED_AS_SUCCESS: 2,
    Verdict.RESULT_MISREPORTED: 3,
}


def verify_claim(claim: Claim, receipts: Iterable[dict[str, Any]]) -> ClaimResult:
    if not claim.tool or not claim.tool.strip():
        return ClaimResult(claim, Verdict.UNVERIFIABLE, "the claim does not name a tool")
    wanted = _norm_tool(claim.tool)
    same_tool = [r for r in receipts if _norm_tool(str(r.get("tool", ""))) == wanted]
    candidates = [r for r in same_tool if _args_match(claim.args, r.get("args"))]
    if not candidates:
        why = (
            "no receipt for that tool"
            if not same_tool
            else "receipts exist for that tool, but none with the claimed arguments"
        )
        return ClaimResult(claim, Verdict.NOT_CALLED, why)
    best: tuple[Verdict, str, dict[str, Any]] | None = None
    for receipt in candidates:
        verdict, reason = _judge(claim, receipt)
        if best is None or _RANK[verdict] < _RANK[best[0]]:
            best = (verdict, reason, receipt)
        if verdict is Verdict.VERIFIED:
            break
    assert best is not None
    return ClaimResult(claim, best[0], best[1], best[2].get("id"))


def verify_claims(claims: Iterable[Claim], receipts: list[dict[str, Any]]) -> list[ClaimResult]:
    return [verify_claim(c, receipts) for c in claims]


# ---------------------------------------------------------------- extractor (a): structured


def extract_structured(transcript: list[dict[str, Any]]) -> list[Claim]:
    """Claims from an Anthropic-style transcript: one per ``tool_use`` block.

    Each ``tool_use`` is the agent asserting "I called this tool with these arguments"; the
    matching ``tool_result`` block (by ``tool_use_id``) says what the agent was shown, so its
    ``is_error`` flag becomes the claimed outcome. This catches a transcript that shows a call
    which no receipt backs, and a call whose recorded status differs from what the agent saw.
    It cannot check what the agent later *wrote* about the result; that needs extractor (b).
    """
    results: dict[str, dict[str, Any]] = {}
    for message in transcript:
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    results[str(block.get("tool_use_id"))] = block
    claims: list[Claim] = []
    for message in transcript:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not (isinstance(block, dict) and block.get("type") == "tool_use"):
                continue
            seen = results.get(str(block.get("id")))
            outcome: Outcome = "unspecified"
            if seen is not None:
                outcome = "failure" if seen.get("is_error") else "success"
            args = block.get("input")
            claims.append(
                Claim(
                    tool=block.get("name") if isinstance(block.get("name"), str) else None,
                    args=args if isinstance(args, dict) else {},
                    outcome=outcome,
                )
            )
    return claims


# ---------------------------------------------------------------- extractor (b): LLM


class LLM(Protocol):
    model: str

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> str: ...


CLAIM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tool": {"type": ["string", "null"]},
                    "args": {"type": "object"},
                    "outcome": {"type": "string", "enum": ["success", "failure", "unspecified"]},
                    "facts": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["tool", "args", "outcome", "facts"],
            },
        }
    },
    "required": ["claims"],
}

SYSTEM_PROMPT = """You extract claims about tool calls from an AI agent's final answer.

A claim is a statement that the agent used a tool, or reports what a tool returned. Output
JSON only: {"claims": [{"tool", "args", "outcome", "facts"}]}.

- tool: one name from the allowed tool list. Use null if the answer implies a tool action but
  you cannot tell which allowed tool it was.
- args: only arguments the answer states explicitly (for example {"to": "bob@example.com"}).
  Use {} if none are stated.
- outcome: "success" if the answer says or implies the call worked, "failure" if it says the
  call failed, "unspecified" if it only says the call was made.
- facts: short exact strings or numbers the answer says the tool returned (a figure, a name,
  a filename). Use [] if none.

Do not extract general knowledge, plans, or statements that are not about a tool call. If the
answer makes no tool claims, return {"claims": []}. Output one claim per distinct tool call."""


def _coerce_claim(raw: Any) -> Claim | None:
    if not isinstance(raw, dict):
        return None
    tool = raw.get("tool")
    args = raw.get("args")
    outcome = raw.get("outcome")
    facts = raw.get("facts")
    return Claim(
        tool=tool if isinstance(tool, str) and tool.strip() else None,
        args=args if isinstance(args, dict) else {},
        outcome=outcome if outcome in ("success", "failure", "unspecified") else "unspecified",
        facts=tuple(str(f) for f in facts if isinstance(f, str | int | float))
        if isinstance(facts, list)
        else (),
    )


def parse_claims(text: str) -> list[Claim]:
    """Parse a model's JSON reply; raises ValueError if it is not the expected shape."""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    data = json.loads(cleaned)
    items = data.get("claims") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("reply has no 'claims' list")
    return [c for c in (_coerce_claim(i) for i in items) if c is not None]


def extract_nl(answer: str, tool_names: list[str], llm: LLM) -> list[Claim]:
    user = f"Allowed tools: {', '.join(tool_names)}\n\nAgent's final answer:\n{answer}"
    return parse_claims(llm.complete_json(SYSTEM_PROMPT, user, CLAIM_SCHEMA))
