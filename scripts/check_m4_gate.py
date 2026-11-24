"""Gate for M4: only run the misreporting study on an extractor good enough to trust.

    uv run python scripts/check_m4_gate.py results/extractor_gemini_eval.json

Exits 0 if VERIFIED recall >= 0.80 and RESULT_MISREPORTED precision >= 0.70, else 1.
Below that, most "misreports" the study finds would be the extractor's own mistakes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

THRESHOLDS = {("VERIFIED", "recall"): 0.80, ("RESULT_MISREPORTED", "precision"): 0.70}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    data = json.loads(Path(argv[1]).read_text("utf-8"))
    ok = True
    for (verdict, metric), minimum in THRESHOLDS.items():
        value = data["per_verdict"][verdict][metric]
        passed = value is not None and value >= minimum
        ok &= passed
        shown = "n/a" if value is None else f"{value:.0%}"
        print(f"{'PASS' if passed else 'FAIL'}  {verdict} {metric} {shown} (need {minimum:.0%})")
    print("GATE PASSED: M4 may start" if ok else "GATE FAILED: do not start M4")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
