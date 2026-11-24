"""Score an extractor against the hand-labelled examples in ``data/labels/``.

End to end per example: extract claims from the answer, verify them against the example's
receipts, and compare each resulting verdict with the hand label.

Matching: predicted and gold claims are paired by normalised tool name (``None`` is its own
group), in order within a tool. For a verdict V:

* TP: a pair where both sides have verdict V
* FP: a predicted V that is unpaired, or paired with a different gold verdict
* FN: a gold V that is unpaired, or paired with a different predicted verdict

An extraction failure (model unreachable or unparseable reply) counts as zero predicted claims,
and is reported separately so it is not mistaken for a clean "no claims" answer.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .claims import Claim, ClaimResult, Verdict, verify_claims

Extract = Callable[[dict[str, Any]], list[Claim]]


def load_examples(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return rows


def gold_claim(raw: dict[str, Any]) -> Claim:
    return Claim(
        tool=raw["tool"],
        args=raw["args"],
        outcome=raw["outcome"],
        facts=tuple(raw["facts"]),
    )


def _group_key(tool: str | None) -> str:
    return "" if not tool else "".join(ch for ch in tool.lower() if ch.isalnum())


def pair_claims(
    predicted: list[ClaimResult], gold: list[tuple[Claim, Verdict]]
) -> tuple[list[tuple[ClaimResult, tuple[Claim, Verdict]]], list[ClaimResult], list[Any]]:
    gold_by: dict[str, list[tuple[Claim, Verdict]]] = defaultdict(list)
    for g in gold:
        gold_by[_group_key(g[0].tool)].append(g)
    pairs: list[tuple[ClaimResult, tuple[Claim, Verdict]]] = []
    extra: list[ClaimResult] = []
    for p in predicted:
        bucket = gold_by.get(_group_key(p.claim.tool))
        if bucket:
            pairs.append((p, bucket.pop(0)))
        else:
            extra.append(p)
    missed = [g for bucket in gold_by.values() for g in bucket]
    return pairs, extra, missed


def evaluate(examples: list[dict[str, Any]], extract: Extract) -> dict[str, Any]:
    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    n_pred = n_gold = n_paired = 0
    failures = 0
    per_example: list[dict[str, Any]] = []
    for ex in examples:
        gold = [(gold_claim(c), Verdict(c["verdict"])) for c in ex["claims"]]
        error: str | None = None
        try:
            claims = extract(ex)
        except Exception as exc:  # noqa: BLE001 - any extractor failure is data, not a crash
            claims, error = [], f"{type(exc).__name__}: {exc}"
            failures += 1
        predicted = verify_claims(claims, ex["receipts"])
        pairs, extra, missed = pair_claims(predicted, gold)
        n_pred += len(predicted)
        n_gold += len(gold)
        n_paired += len(pairs)
        for p, (_, g_verdict) in pairs:
            confusion[g_verdict.value][p.verdict.value] += 1
            if p.verdict == g_verdict:
                tp[g_verdict.value] += 1
            else:
                fp[p.verdict.value] += 1
                fn[g_verdict.value] += 1
        for p in extra:
            fp[p.verdict.value] += 1
            confusion["(no gold claim)"][p.verdict.value] += 1
        for _, g_verdict in missed:
            fn[g_verdict.value] += 1
            confusion[g_verdict.value]["(claim not found)"] += 1
        per_example.append(
            {
                "id": ex["id"],
                "error": error,
                "predicted": [r.to_dict() for r in predicted],
                "gold_verdicts": [v.value for _, v in gold],
            }
        )

    def ratio(a: int, b: int) -> float | None:
        return round(a / b, 4) if b else None

    per_verdict: dict[str, dict[str, Any]] = {}
    for v in Verdict:
        k = v.value
        per_verdict[k] = {
            "precision": ratio(tp[k], tp[k] + fp[k]),
            "recall": ratio(tp[k], tp[k] + fn[k]),
            "tp": tp[k],
            "fp": fp[k],
            "fn": fn[k],
            "support": tp[k] + fn[k],
        }
    return {
        "examples": len(examples),
        "gold_claims": n_gold,
        "predicted_claims": n_pred,
        "claims_paired_by_tool": n_paired,
        "claim_detection_precision": ratio(n_paired, n_pred),
        "claim_detection_recall": ratio(n_paired, n_gold),
        "extraction_failures": failures,
        "per_verdict": per_verdict,
        "confusion_gold_to_predicted": {k: dict(v) for k, v in confusion.items()},
        "per_example": per_example,
    }
