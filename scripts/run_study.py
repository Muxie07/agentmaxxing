"""M4 step 1: run every task x fault x repeat against one model, recording signed receipts.

    uv run python scripts/run_study.py --model MODEL --runs 3            (gemini-* models)
    uv run python scripts/run_study.py --model MODEL --limit 2 --runs 1  (smoke test)

Writes results/study/<model>/<task>/<fault>/run<k>/{receipts.jsonl,run.json} and the study's
public key results/study/<model>/study.pub (the private key stays out of git: *.key).
Resumable: runs that already have run.json are skipped. Stops early if the first 3 runs fail
with the same error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from agentmaxxing.keys import generate, load_private
from agentmaxxing.llm import GeminiClient
from agentmaxxing.study.agent import load_tasks, run_task
from agentmaxxing.study.faults import ALL_FAULTS, Fault
from agentmaxxing.study.gemini_chat import GeminiChat

ROOT = Path(__file__).resolve().parent.parent


def slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", model)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--faults", default=",".join(f.value for f in ALL_FAULTS))
    parser.add_argument("--tasks", default=str(ROOT / "data/study/tasks.jsonl"))
    parser.add_argument("--limit", type=int, help="only the first N tasks (smoke test)")
    parser.add_argument("--out", default=str(ROOT / "results/study"))
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    if not args.model.startswith(("gemini-", "gemma-")):
        print("only gemini-*/gemma-* models are wired up for the study so far", file=sys.stderr)
        return 2
    tasks = load_tasks(Path(args.tasks))[: args.limit or None]
    faults = [Fault(f) for f in args.faults.split(",")]
    base = Path(args.out) / slug(args.model)
    base.mkdir(parents=True, exist_ok=True)
    key_prefix = base / "study"
    if not key_prefix.with_suffix(".key").exists():
        generate(key_prefix)
    key = load_private(key_prefix.with_suffix(".key"))

    client = GeminiClient(args.model, env_file=ROOT / ".env", seed=args.seed)
    chat = GeminiChat(client)
    errors: list[str] = []
    done = skipped = 0
    for task in tasks:
        for fault in faults:
            for k in range(1, args.runs + 1):
                run_dir = base / task.id / fault.value / f"run{k}"
                if (run_dir / "run.json").exists():
                    skipped += 1
                    continue
                run_dir.mkdir(parents=True, exist_ok=True)
                log = run_dir / "receipts.jsonl"
                log.unlink(missing_ok=True)
                try:
                    result = run_task(chat, task, fault, log, key)
                except Exception as exc:  # noqa: BLE001 - recorded, and fail-fast below
                    errors.append(f"{type(exc).__name__}: {exc}")
                    print(f"\n{task.id}/{fault.value}/run{k}: {errors[-1][:200]}", file=sys.stderr)
                    if len(errors) == 3 and done == 0 and len(set(errors)) == 1:
                        print("aborted: first 3 runs failed with the same error", file=sys.stderr)
                        return 1
                    continue
                record = {
                    **result.to_dict(),
                    "model": args.model,
                    "model_version": client.model_version,
                    "run": k,
                    "seed": args.seed,
                    "temperature": client.temperature,
                    "date_utc": datetime.now(UTC).isoformat(timespec="seconds"),
                }
                (run_dir / "run.json").write_text(
                    json.dumps(record, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                done += 1
                print(".", end="", flush=True, file=sys.stderr)
    print(f"\ndone {done}, skipped {skipped}, failed {len(errors)}", file=sys.stderr)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
