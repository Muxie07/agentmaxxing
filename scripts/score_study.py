"""M4 step 2: score every recorded run and write results/study_summary.json.

    uv run python scripts/score_study.py --extractor MODEL \
        --extractor-eval results/extractor_gemini_eval.json

Each run's receipt log is verified against the study key first; a run whose log fails is
excluded and counted. Refuses to score unless the extractor eval passes the M4 gate
(scripts/check_m4_gate.py); --allow-ungated overrides and marks the summary "ungated".
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agentmaxxing.claims import extract_nl
from agentmaxxing.keys import load_public
from agentmaxxing.llm import make_client
from agentmaxxing.study.agent import TOOL_NAMES
from agentmaxxing.study.score import score_run, summarize
from agentmaxxing.verify import verify_log

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from check_m4_gate import THRESHOLDS  # noqa: E402


def gate_passes(path: Path) -> bool:
    data = json.loads(path.read_text("utf-8"))
    for (verdict, metric), minimum in THRESHOLDS.items():
        value = data["per_verdict"][verdict][metric]
        if value is None or value < minimum:
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extractor", required=True, help="model used to extract claims")
    parser.add_argument("--extractor-eval", required=True, help="results/*_eval.json for it")
    parser.add_argument("--allow-ungated", action="store_true")
    parser.add_argument("--study", default=str(ROOT / "results/study"))
    parser.add_argument("--out", default=str(ROOT / "results"))
    args = parser.parse_args()

    gated = gate_passes(Path(args.extractor_eval))
    if not gated and not args.allow_ungated:
        print("extractor fails the M4 gate; refusing to score (see check_m4_gate.py)")
        return 1
    llm = make_client(args.extractor, env_file=ROOT / ".env")
    records: list[dict[str, Any]] = []
    excluded = 0
    for model_dir in sorted(p for p in Path(args.study).iterdir() if p.is_dir()):
        pub = load_public(model_dir / "study.pub")
        for run_file in sorted(model_dir.rglob("run.json")):
            run = json.loads(run_file.read_text("utf-8"))
            log = run_file.parent / "receipts.jsonl"
            receipts: list[dict[str, Any]] = []
            if log.exists():
                if not verify_log(log, pub).ok:
                    excluded += 1
                    continue
                receipts = [json.loads(x) for x in log.read_text("utf-8").splitlines() if x]
            score = score_run(
                run["answer"], receipts, lambda a: extract_nl(a, list(TOOL_NAMES), llm)
            )
            records.append(
                {**{k: run[k] for k in ("model", "task_id", "fault", "run")}, "score": score}
            )
            print(".", end="", flush=True, file=sys.stderr)
    out = Path(args.out)
    with (out / "study_scored.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    summary = {
        "extractor": args.extractor,
        "extractor_eval": Path(args.extractor_eval).name,
        "ungated": not gated,
        "runs_scored": len(records),
        "runs_excluded_bad_log": excluded,
        "rows": summarize(records),
    }
    (out / "study_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"\nscored {len(records)}, excluded {excluded}; wrote results/study_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
