# agentmaxxing

Signed, tamper-evident receipts for every real tool call an AI agent makes, a verifier that
checks an agent's final answer against those receipts, and a measured study of how often real
models misreport tool outcomes.

> Status: under construction. Milestones M0 (scaffold), M1 (receipts), M2 (MCP stdio proxy) and M3 (claim verification) are in place.
> Nothing in this README is a measured result yet; numbers will appear only when a committed
> script produces them under `results/`.

## Quickstart (receipts)

```bash
uv sync
uv run agentmaxxing keygen --out keys/agent        # writes agent.key and agent.pub
uv run agentmaxxing verify calls.jsonl --pubkey keys/agent.pub
```

Record receipts from any stdio MCP server without changing the agent:

```bash
uv run agentmaxxing proxy --key keys/agent.key --log calls.jsonl -- <your MCP server command>
```

Claude Desktop setup: [docs/claude-desktop.md](docs/claude-desktop.md).

See [docs/receipts.md](docs/receipts.md) for the receipt format and exactly what verification
does and does not catch.

## Claim verification (M3)

`agentmaxxing check` verifies a log, then checks an agent's answer against it:

```bash
uv run agentmaxxing check --log calls.jsonl --pubkey keys/agent.pub --answer answer.txt --tools search,send_email
```

Verdicts: `VERIFIED`, `NOT_CALLED`, `FAILED_REPORTED_AS_SUCCESS`, `RESULT_MISREPORTED`,
`UNVERIFIABLE`. The verifier is deterministic and tested against all 110 Claude-written labels; the
claim *extractor* is what is measured below. Two extractors exist: structured (from transcript
`tool_use` blocks, exact) and natural-language (a local LLM with a JSON schema). Labels and rules:
[docs/labelling.md](docs/labelling.md).

### How well the natural-language extractor works

This is a weak first result with a small local model, and the labels are single-annotator
(see docs/labelling.md). Treat a verdict from the NL path as a lead to check, not a finding.

<!-- extractor-table:start -->
All runs (labels written by Claude; human review of 20 pending):

| Run | Model | Date | VERIFIED recall | RESULT_MISREPORTED precision | Claim detection recall | Source |
|---|---|---|---|---|---|---|
| extractor (detailed below) | `deepseek-r1:latest` | 2026-11-24 | 21% | 28% | 60% | [extractor_eval.json](results/extractor_eval.json) |

Detailed: model `deepseek-r1:latest` (Ollama 0.6.5, temperature 0.0, seed 0), run 2026-11-24 on 110 labelled examples (113 claims). Source: [results/extractor_eval.json](results/extractor_eval.json).

| Verdict | Precision | Recall | Support |
|---|---|---|---|
| VERIFIED | 90% | 21% | 43 |
| NOT_CALLED | 30% | 50% | 20 |
| FAILED_REPORTED_AS_SUCCESS | 91% | 50% | 20 |
| RESULT_MISREPORTED | 28% | 45% | 20 |
| UNVERIFIABLE | 18% | 60% | 10 |

Where the labels and the pipeline disagree (rows: gold label; columns: what the pipeline concluded; source: [results/extractor_confusion.json](results/extractor_confusion.json)):

| Gold label | VERIFIED | NOT_CALLED | FAILED_REPORTED_AS_SUCCESS | RESULT_MISREPORTED | UNVERIFIABLE | (claim not found) |
|---|---|---|---|---|---|---|
| VERIFIED | 9 | 0 | 0 | 22 | 0 | 12 |
| NOT_CALLED | 0 | 10 | 0 | 1 | 0 | 9 |
| FAILED_REPORTED_AS_SUCCESS | 0 | 0 | 10 | 0 | 0 | 10 |
| RESULT_MISREPORTED | 1 | 0 | 0 | 9 | 0 | 10 |
| UNVERIFIABLE | 0 | 0 | 0 | 0 | 6 | 4 |
| (no gold claim) | 0 | 23 | 1 | 0 | 28 | 0 |

Finding the claims at all (paired by tool name): precision 57%, recall 60%. Extraction failures: 0.
<!-- extractor-table:end -->

Where it is weak, from the table above:

- It reports **false alarms**: many correctly reported calls come out as `RESULT_MISREPORTED`,
  because the model writes "facts" as phrases ("128 rows", "HTTP 200") that are not literal
  substrings of the recorded result, and the verifier does not guess at paraphrase.
- It **adds claims** the labels do not contain (the "(no gold claim)" row): claims with no tool
  name, and claims about a tool that has no receipt. I have not inspected every case, so the
  split between genuine over-extraction and label gaps is unknown. These extras lower precision
  for `NOT_CALLED` and `UNVERIFIABLE` in particular.
- Rounding is not forgiven ("about 545,000" vs 545,796).
- Not tried: a larger or hosted model, prompt tuning, or a held-out split. The prompt was not
  tuned on these labels; tuning on them would need a separate test set.

Reproduce: `uv run python scripts/eval_extractor.py` (needs Ollama and the model), then
`uv run python scripts/replay_extractor_eval.py` and `uv run python scripts/render_extractor_table.py`.

## Prior art and what's different

To be written in M5. It will credit `moshe-ship/toolproof`, `sumankrsh/mcp-gatekeeper` and
`darshansatpathy/agent-guardrails-gateway`.
