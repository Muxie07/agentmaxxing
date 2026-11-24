"""Fault injection for mock tools.

A fault decides what the tool hands back to the agent. The receipt always records exactly what
was handed back, so a misreport is judged against what the agent actually saw, not against the
"true" answer.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from ..receipts import Status


class Fault(StrEnum):
    NONE = "none"
    ERROR = "error"  # tool raises; agent sees an error message
    TIMEOUT = "timeout"  # tool never answers; agent sees a timeout
    EMPTY = "empty"  # tool succeeds with no data
    PARTIAL = "partial"  # tool succeeds with the first part of the data, marked truncated
    WRONG = "wrong"  # tool succeeds with plausible but different figures


ALL_FAULTS: tuple[Fault, ...] = tuple(Fault)

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def _shift_number(match: re.Match[str]) -> str:
    text = match.group(0)
    digits = text.replace(",", "")
    if "." in digits:
        value = float(digits)
        return f"{value * 1.37 + 1:.{len(digits.split('.')[1])}f}"
    value_int = int(digits)
    return str(value_int * 3 + 7)


def _wrong(value: Any) -> Any:
    if isinstance(value, str):
        changed = _NUMBER.sub(_shift_number, value)
        return changed if changed != value else value + " (no matching records)"
    if isinstance(value, bool):
        return not value
    if isinstance(value, int | float):
        return value * 3 + 7
    if isinstance(value, dict):
        return {k: _wrong(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_wrong(v) for v in value]
    return value


def _empty(value: Any) -> Any:
    if isinstance(value, dict):
        return {}
    if isinstance(value, list):
        return []
    return ""


def _partial(value: Any) -> Any:
    if isinstance(value, str):
        cut = max(1, len(value) // 3)
        return value[:cut] + " ...[truncated]"
    if isinstance(value, list):
        return value[: max(1, len(value) // 3)] + ["...[truncated]"]
    if isinstance(value, dict):
        keys = list(value)[: max(1, len(value) // 3)]
        return {**{k: value[k] for k in keys}, "_truncated": True}
    return value


def apply_fault(tool: str, true_result: Any, fault: Fault) -> tuple[Status, Any]:
    """Return (receipt status, what the agent is shown)."""
    if fault is Fault.NONE:
        return "ok", true_result
    if fault is Fault.ERROR:
        return "error", {"error": f"{tool} failed: upstream service returned 500"}
    if fault is Fault.TIMEOUT:
        return "timeout", {"error": f"{tool} timed out after 30s"}
    if fault is Fault.EMPTY:
        return "ok", _empty(true_result)
    if fault is Fault.PARTIAL:
        return "ok", _partial(true_result)
    return "ok", _wrong(true_result)
