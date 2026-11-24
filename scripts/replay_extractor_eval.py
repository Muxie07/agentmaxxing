"""Recompute the extractor metrics from the saved raw model replies (no model needed).

Proves results/extractor_eval.json follows from results/extractor_raw.jsonl plus the committed
labels and verifier, and writes the confusion matrix to results/extractor_confusion.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentmaxxing.claims import Claim, parse_claims
from agentmaxxing.extractor_eval import evaluate, load_examples

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    stored = json.loads((ROOT / "results/extractor_eval.json").read_text("utf-8"))
    raw = {
        row["id"]: row["model_call"]
        for row in (
            json.loads(ln)
            for ln in (ROOT / "results/extractor_raw.jsonl").read_text("utf-8").splitlines()
        )
    }
    examples = load_examples(ROOT / "data/labels/examples.jsonl")

    def replay(ex: dict[str, Any]) -> list[Claim]:
        call = raw[ex["id"]]
        if call["error"]:
            raise ValueError(call["error"])
        return parse_claims(call["raw"])

    report = evaluate(examples, replay)
    for key in (
        "examples",
        "gold_claims",
        "predicted_claims",
        "per_verdict",
        "claim_detection_precision",
        "claim_detection_recall",
        "extraction_failures",
    ):
        if report[key] != stored[key]:
            print(f"MISMATCH in {key}")
            return 1
    out = {
        "source": "replayed from results/extractor_raw.jsonl",
        "confusion_gold_to_predicted": report["confusion_gold_to_predicted"],
    }
    (ROOT / "results/extractor_confusion.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print("replay matches results/extractor_eval.json; wrote results/extractor_confusion.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
