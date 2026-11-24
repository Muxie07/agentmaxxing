from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agentmaxxing.claims import (
    Claim,
    Verdict,
    extract_nl,
    extract_structured,
    parse_claims,
    verify_claim,
    verify_claims,
)
from agentmaxxing.extractor_eval import evaluate, gold_claim, load_examples

LABELS = Path(__file__).parent.parent / "data" / "labels" / "examples.jsonl"


def rec(
    tool: str, args: dict[str, Any], status: str, result: Any, rid: str = "r1"
) -> dict[str, Any]:
    return {"id": rid, "tool": tool, "args": args, "status": status, "result": result}


# ---- the hand labels and the verifier must agree (catches label typos and verifier bugs)


def test_label_set_is_big_enough_and_covers_every_verdict() -> None:
    examples = load_examples(LABELS)
    assert len(examples) >= 100
    seen = {c["verdict"] for ex in examples for c in ex["claims"]}
    assert seen == {v.value for v in Verdict}


def test_verifier_reproduces_every_hand_label_from_gold_claims() -> None:
    wrong: list[str] = []
    for ex in load_examples(LABELS):
        results = verify_claims([gold_claim(c) for c in ex["claims"]], ex["receipts"])
        for r, c in zip(results, ex["claims"], strict=True):
            if r.verdict.value != c["verdict"]:
                wrong.append(f"{ex['id']}: label {c['verdict']}, verifier {r.verdict.value}")
    assert wrong == []


def test_perfect_extractor_scores_one_everywhere() -> None:
    examples = load_examples(LABELS)
    by_answer = {ex["answer"]: ex for ex in examples}

    def oracle(ex: dict[str, Any]) -> list[Claim]:
        return [gold_claim(c) for c in by_answer[ex["answer"]]["claims"]]

    report = evaluate(examples, oracle)
    assert report["claim_detection_precision"] == 1.0
    assert report["claim_detection_recall"] == 1.0
    for stats in report["per_verdict"].values():
        assert stats["precision"] == 1.0 and stats["recall"] == 1.0


def test_extractor_that_finds_nothing_has_zero_recall_and_no_precision() -> None:
    report = evaluate(load_examples(LABELS), lambda ex: [])
    assert report["claim_detection_recall"] == 0.0
    assert report["claim_detection_precision"] is None
    assert report["per_verdict"]["NOT_CALLED"]["recall"] == 0.0


def test_extractor_exception_is_counted_not_hidden() -> None:
    def boom(ex: dict[str, Any]) -> list[Claim]:
        raise ValueError("bad reply")

    report = evaluate(load_examples(LABELS)[:3], boom)
    assert report["extraction_failures"] == 3
    assert report["per_example"][0]["error"] == "ValueError: bad reply"


# ---- verifier behaviour, one rule at a time


def test_not_called_when_no_receipt() -> None:
    r = verify_claim(Claim("send_email", {}, "success"), [rec("search", {}, "ok", "x")])
    assert r.verdict is Verdict.NOT_CALLED


def test_not_called_when_args_differ() -> None:
    receipts = [rec("send_email", {"to": "a@x.com"}, "ok", "sent")]
    r = verify_claim(Claim("send_email", {"to": "b@x.com"}, "success"), receipts)
    assert r.verdict is Verdict.NOT_CALLED
    assert "claimed arguments" in r.reason


def test_tool_names_match_loosely() -> None:
    receipts = [rec("send_email", {}, "ok", "sent")]
    assert verify_claim(Claim("Send-Email"), receipts).verdict is Verdict.VERIFIED


@pytest.mark.parametrize("status", ["error", "timeout", "cancelled"])
def test_failed_reported_as_success(status: str) -> None:
    r = verify_claim(Claim("read_file", {}, "success"), [rec("read_file", {}, status, "x")])
    assert r.verdict is Verdict.FAILED_REPORTED_AS_SUCCESS


def test_failure_claim_matching_a_failed_receipt_is_verified() -> None:
    r = verify_claim(Claim("read_file", {}, "failure"), [rec("read_file", {}, "error", "x")])
    assert r.verdict is Verdict.VERIFIED


def test_failure_claimed_but_call_succeeded_is_misreported() -> None:
    r = verify_claim(Claim("read_file", {}, "failure"), [rec("read_file", {}, "ok", "x")])
    assert r.verdict is Verdict.RESULT_MISREPORTED


def test_fact_checks_are_case_and_number_format_insensitive() -> None:
    receipt = [rec("calculator", {}, "ok", "Total: 1,234.50 USD")]
    assert verify_claim(Claim("calculator", {}, "success", ("1234.5",)), receipt).verdict is (
        Verdict.VERIFIED
    )
    assert verify_claim(Claim("calculator", {}, "success", ("total",)), receipt).verdict is (
        Verdict.VERIFIED
    )
    assert verify_claim(Claim("calculator", {}, "success", ("999",)), receipt).verdict is (
        Verdict.RESULT_MISREPORTED
    )


def test_any_matching_ok_receipt_beats_an_earlier_failure() -> None:
    receipts = [
        rec("send_email", {"to": "a@x"}, "error", "bounced", "r1"),
        rec("send_email", {"to": "a@x"}, "ok", "sent", "r2"),
    ]
    r = verify_claim(Claim("send_email", {"to": "a@x"}, "success"), receipts)
    assert r.verdict is Verdict.VERIFIED and r.receipt_id == "r2"


def test_truncated_and_redacted_results_are_unverifiable_not_wrong() -> None:
    truncated = rec("read_file", {}, "ok", {"_truncated": True, "preview": "abc"})
    redacted = rec("http_get", {}, "ok", {"token": "[REDACTED]"})
    assert verify_claim(Claim("read_file", {}, "success", ("zzz",)), [truncated]).verdict is (
        Verdict.UNVERIFIABLE
    )
    assert verify_claim(Claim("http_get", {}, "success", ("zzz",)), [redacted]).verdict is (
        Verdict.UNVERIFIABLE
    )


def test_redacted_argument_does_not_count_against_a_claim() -> None:
    receipts = [rec("http_get", {"api_key": "[REDACTED]", "url": "u"}, "ok", "x")]
    claim = Claim("http_get", {"api_key": "sk-1", "url": "u"}, "success")
    assert verify_claim(claim, receipts).verdict is Verdict.VERIFIED


def test_claim_without_tool_is_unverifiable() -> None:
    assert verify_claim(Claim(None), []).verdict is Verdict.UNVERIFIABLE


# ---- extractor (a): structured


def test_structured_extractor_reads_tool_use_and_result_blocks() -> None:
    transcript = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "a"}},
                {"type": "tool_use", "id": "t2", "name": "send_email", "input": {"to": "x"}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
                {"type": "tool_result", "tool_use_id": "t2", "content": "no", "is_error": True},
            ],
        },
    ]
    claims = extract_structured(transcript)
    assert [(c.tool, c.outcome) for c in claims] == [
        ("read_file", "success"),
        ("send_email", "failure"),
    ]
    assert claims[0].args == {"path": "a"}
    # transcript says the email failed, receipts say it succeeded -> flagged
    receipts = [
        rec("read_file", {"path": "a"}, "ok", "x"),
        rec("send_email", {"to": "x"}, "ok", "y"),
    ]
    verdicts = [r.verdict for r in verify_claims(claims, receipts)]
    assert verdicts == [Verdict.VERIFIED, Verdict.RESULT_MISREPORTED]


def test_structured_extractor_flags_a_call_with_no_receipt() -> None:
    transcript = [
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "t1", "name": "search", "input": {}}],
        }
    ]
    (r,) = verify_claims(extract_structured(transcript), [])
    assert r.verdict is Verdict.NOT_CALLED


# ---- extractor (b): natural language, with a fake model


class FakeLLM:
    model = "fake"

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompt = ""

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> str:
        self.prompt = user
        assert schema["required"] == ["claims"]
        return self.reply


def test_nl_extractor_parses_model_json_and_passes_tool_list() -> None:
    reply = json.dumps(
        {
            "claims": [
                {"tool": "send_email", "args": {"to": "a@x"}, "outcome": "success", "facts": []},
                {"tool": None, "args": "bad", "outcome": "weird", "facts": [3, "x", None]},
            ]
        }
    )
    llm = FakeLLM(reply)
    claims = extract_nl("I emailed a@x.", ["search", "send_email"], llm)
    assert "search, send_email" in llm.prompt
    assert claims[0] == Claim("send_email", {"to": "a@x"}, "success", ())
    assert claims[1] == Claim(None, {}, "unspecified", ("3", "x"))  # bad fields are coerced


def test_parse_claims_strips_think_blocks_and_rejects_wrong_shape() -> None:
    assert parse_claims('<think>hmm</think>{"claims": []}') == []
    with pytest.raises(ValueError):
        parse_claims('{"nope": 1}')
    with pytest.raises(ValueError):
        parse_claims("not json at all")
