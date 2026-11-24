"""Evaluate the NL claim extractor against data/labels/examples.jsonl.

    uv run python scripts/eval_extractor.py --model deepseek-r1:latest
    uv run python scripts/eval_extractor.py --model gemini-2.5-flash --out-prefix extractor_gemini

Writes results/<prefix>_eval.json (metrics and run metadata) and results/<prefix>_raw.jsonl
(every raw model reply). Ollama models need a running Ollama; gemini-* models need
GEMINI_API_KEY in the environment or .env (the key is never written to results).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentmaxxing.claims import SYSTEM_PROMPT, Claim, extract_nl
from agentmaxxing.extractor_eval import EvaluationAborted, evaluate, load_examples
from agentmaxxing.llm import DEFAULT_HOST, GeminiClient, OllamaClient, make_client

ROOT = Path(__file__).resolve().parent.parent


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ollama_version(host: str) -> str | None:
    try:
        with urllib.request.urlopen(f"{host}/api/version", timeout=10) as r:  # noqa: S310
            version = json.load(r).get("version")
            return version if isinstance(version, str) else None
    except OSError:
        return None


class Recorder:
    """Wraps a client, keeping every raw reply and its latency."""

    def __init__(self, inner: OllamaClient | GeminiClient) -> None:
        self.inner = inner
        self.model = inner.model
        self.rows: list[dict[str, Any]] = []
        self.current = ""

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> str:
        started = time.monotonic()
        raw = ""
        error: str | None = None
        try:
            raw = self.inner.complete_json(system, user, schema)
            return raw
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self.rows.append(
                {
                    "id": self.current,
                    "seconds": round(time.monotonic() - started, 2),
                    "raw": raw,
                    "error": error,
                }
            )


FAIL_FAST_AFTER = 3


def fails_fast(rows: list[dict[str, Any]]) -> None:
    """Stop the run (writing nothing) if the first calls all fail with the same error.

    A broken setup (wrong model id, bad key, no network) would otherwise produce a results
    file of 0% scores that looks like a measurement.
    """
    if len(rows) != FAIL_FAST_AFTER:
        return
    errors = {row["error"] for row in rows}
    if len(errors) == 1 and None not in errors:
        raise EvaluationAborted(f"first {FAIL_FAST_AFTER} calls failed: {next(iter(errors))}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="deepseek-r1:latest")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--labels", default=str(ROOT / "data" / "labels" / "examples.jsonl"))
    parser.add_argument("--out", default=str(ROOT / "results"))
    parser.add_argument("--limit", type=int, help="only the first N examples (smoke test)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--out-prefix",
        default="extractor",
        help="file prefix under --out (default: extractor; use another to keep earlier runs)",
    )
    args = parser.parse_args()

    labels = Path(args.labels)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    examples = load_examples(labels)
    if args.limit:
        examples = examples[: args.limit]

    client = make_client(
        args.model, host=args.host, temperature=0.0, seed=args.seed, env_file=ROOT / ".env"
    )
    recorder = Recorder(client)

    def extract(ex: dict[str, Any]) -> list[Claim]:
        recorder.current = ex["id"]
        print(f"{ex['id']} ", end="", flush=True, file=sys.stderr)
        try:
            return extract_nl(ex["answer"], ex["tools"], recorder)
        finally:
            fails_fast(recorder.rows)

    started = time.monotonic()
    try:
        report = evaluate(examples, extract)
    except EvaluationAborted as exc:
        print(f"\naborted, no results written: {exc}", file=sys.stderr)
        return 1
    elapsed = round(time.monotonic() - started, 1)
    print(file=sys.stderr)

    per_example = report.pop("per_example")
    meta = {
        "model": args.model,
        "provider": "gemini" if isinstance(client, GeminiClient) else "ollama",
        "ollama_version": ollama_version(args.host) if isinstance(client, OllamaClient) else None,
        "model_version": client.model_version if isinstance(client, GeminiClient) else None,
        "api_retries": client.retries if isinstance(client, GeminiClient) else 0,
        "schema_fallbacks": client.schema_fallbacks if isinstance(client, GeminiClient) else 0,
        "date_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "temperature": 0.0,
        "seed": args.seed,
        "think": False,
        "machine": f"{platform.system()} {platform.machine()}, python {platform.python_version()}",
        "labels_file": str(labels.relative_to(ROOT))
        if labels.is_relative_to(ROOT)
        else str(labels),
        "labels_sha256": sha256_file(labels),
        "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "total_seconds": elapsed,
        "mean_seconds_per_example": round(elapsed / max(len(examples), 1), 2),
        "partial_run": bool(args.limit),
    }
    (out / f"{args.out_prefix}_eval.json").write_text(
        json.dumps({"meta": meta, **report}, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    with (out / f"{args.out_prefix}_raw.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        raw_by_id = {r["id"]: r for r in recorder.rows}
        for row in per_example:
            fh.write(
                json.dumps({**row, "model_call": raw_by_id.get(row["id"])}, ensure_ascii=False)
                + "\n"
            )
    print(f"wrote {out / (args.out_prefix + '_eval.json')}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
