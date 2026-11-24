"""Fill the extractor-results block in README.md from results/extractor_eval.json."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
START, END = "<!-- extractor-table:start -->", "<!-- extractor-table:end -->"


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def main() -> None:
    data = json.loads((ROOT / "results/extractor_eval.json").read_text("utf-8"))
    meta = data["meta"]
    lines = [
        START,
        f"Model `{meta['model']}` (Ollama {meta['ollama_version']}, temperature "
        f"{meta['temperature']}, seed {meta['seed']}), run {meta['date_utc'][:10]} on "
        f"{data['examples']} hand-labelled examples ({data['gold_claims']} claims). Source: "
        "[results/extractor_eval.json](results/extractor_eval.json).",
        "",
        "| Verdict | Precision | Recall | Support |",
        "|---|---|---|---|",
    ]
    for verdict, s in data["per_verdict"].items():
        lines.append(f"| {verdict} | {pct(s['precision'])} | {pct(s['recall'])} | {s['support']} |")
    conf = json.loads((ROOT / "results/extractor_confusion.json").read_text("utf-8"))
    matrix = conf["confusion_gold_to_predicted"]
    cols = [*[v for v in data["per_verdict"]], "(claim not found)"]
    lines += [
        "",
        "Where the labels and the pipeline disagree (rows: hand label; columns: what "
        "the pipeline concluded; source: "
        "[results/extractor_confusion.json](results/extractor_confusion.json)):",
        "",
        "| Hand label | " + " | ".join(cols) + " |",
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
