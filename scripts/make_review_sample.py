"""Write docs/label_review.md: 20 randomly chosen labelled examples (seeded) for human review."""

from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
rows = [
    json.loads(ln)
    for ln in (ROOT / "data/labels/examples.jsonl").read_text("utf-8").splitlines()
    if ln.strip()
]
sample = sorted(random.Random(20260101).sample(rows, 20), key=lambda r: r["id"])
out = [
    "# Label review sample (20 examples)\n",
    "Chosen with `random.Random(20260101)` by `scripts/make_review_sample.py`. For each, decide",
    "whether the **verdict** is right under `docs/labelling.md`. Mark `[x] agree` or write a",
    "correction. Return the file to confirm the labels.\n",
]
for r in sample:
    out.append(f"## {r['id']}\n")
    out.append(f"**Answer:** {r['answer']}\n")
    out.append("**Receipts (what really happened):**")
    for x in r["receipts"]:
        out.append(
            f"- `{x['tool']}` {json.dumps(x['args'])} -> **{x['status']}**: "
            f"{json.dumps(x['result'])[:160]}"
        )
    if not r["receipts"]:
        out.append("- (none)")
    out.append("\n**Gold claims and verdicts:**")
    for c in r["claims"]:
        out.append(
            f"- tool={c['tool']} args={json.dumps(c['args'])} outcome={c['outcome']} "
            f"facts={json.dumps(c['facts'])} -> **{c['verdict']}**"
        )
    if not r["claims"]:
        out.append("- (no tool claims)")
    out.append("\n- [ ] agree   - [ ] disagree: ____________\n")
(ROOT / "docs/label_review.md").write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
print("wrote docs/label_review.md")
