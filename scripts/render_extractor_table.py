"""Fill the extractor-results block in README.md.

Detailed tables come from the primary run (results/extractor_eval.json by default); a short
comparison row is added for every results/*_eval.json, so earlier runs are never dropped.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
START, END = "<!-- extractor-table:start -->", "<!-- extractor-table:end -->"


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def runtime(meta: dict[str, Any]) -> str:
    if meta.get("provider") == "gemini":
        version = meta.get("model_version") or meta["model"]
        return f"Gemini API, served as `{version}`"
    return f"Ollama {meta.get('ollama_version')}"


def comparison(primary: str) -> list[str]:
    rows = [
        "| Run | Model | Date | VERIFIED recall | RESULT_MISREPORTED precision "
        "| Claim detection recall | Source |",
        "|---|---|---|---|---|---|---|",
    ]
    for path in sorted((ROOT / "results").glob("*_eval.json")):
        d = json.loads(path.read_text("utf-8"))
        m, pv = d["meta"], d["per_verdict"]
        mark = " (detailed below)" if path.name == primary else ""
        rows.append(
            f"| {path.stem.removesuffix('_eval')}{mark} | `{m['model']}` | {m['date_utc'][:10]} "
            f"| {pct(pv['VERIFIED']['recall'])} | {pct(pv['RESULT_MISREPORTED']['precision'])} "
            f"| {pct(d['claim_detection_recall'])} | [{path.name}](results/{path.name}) |"
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary", default="extractor_eval.json", help="file under results/")
    parser.add_argument("--confusion", default="extractor_confusion.json")
    args = parser.parse_args()
    data = json.loads((ROOT / "results" / args.primary).read_text("utf-8"))
    meta = data["meta"]
    lines = [
        START,
        "All runs (labels written by Claude; human review of 20 pending):",
        "",
        *comparison(args.primary),
        "",
        f"Detailed: model `{meta['model']}` ({runtime(meta)}, temperature "
        f"{meta['temperature']}, seed {meta['seed']}), run {meta['date_utc'][:10]} on "
        f"{data['examples']} labelled examples ({data['gold_claims']} claims). Source: "
        f"[results/{args.primary}](results/{args.primary}).",
        "",
        "| Verdict | Precision | Recall | Support |",
        "|---|---|---|---|",
    ]
    for verdict, s in data["per_verdict"].items():
        lines.append(f"| {verdict} | {pct(s['precision'])} | {pct(s['recall'])} | {s['support']} |")
    conf = json.loads((ROOT / "results" / args.confusion).read_text("utf-8"))
    matrix = conf["confusion_gold_to_predicted"]
    cols = [*[v for v in data["per_verdict"]], "(claim not found)"]
    lines += [
        "",
        "Where the labels and the pipeline disagree (rows: gold label; columns: what "
        "the pipeline concluded; source: "
        f"[results/{args.confusion}](results/{args.confusion})):",
        "",
        "| Gold label | " + " | ".join(cols) + " |",
        "|---|" + "---|" * len(cols),
    ]
    for row in [*data["per_verdict"], "(no gold claim)"]:
        cells = [str(matrix.get(row, {}).get(c, 0)) for c in cols]
        lines.append(f"| {row} | " + " | ".join(cells) + " |")
    lines += [
        "",
        f"Finding the claims at all (paired by tool name): precision "
        f"{pct(data['claim_detection_precision'])}, recall {pct(data['claim_detection_recall'])}. "
        f"Extraction failures: {data['extraction_failures']}.",
        END,
    ]
    readme = ROOT / "README.md"
    text = readme.read_text("utf-8")
    block = "\n".join(lines)
    if START in text:
        head, rest = text.split(START, 1)
        text = head + block + rest.split(END, 1)[1]
    else:
        raise SystemExit(f"README.md has no {START} marker")
    readme.write_text(text, encoding="utf-8", newline="\n")
    print("README.md updated")


if __name__ == "__main__":
    main()
