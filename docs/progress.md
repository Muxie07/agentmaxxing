# Progress

Handback reports are appended below, one per milestone.

## M0 Scaffold

```
MILESTONE: M0 Scaffold
STATUS: done
COMMIT: 5155964 M0: scaffold (uv project, CLI entry point, CI, Makefile, license, README skeleton)
TESTS: 2/2, `uv run pytest tests/test_cli_help.py`, coverage not measured
CI: not run (workflow written, nothing pushed)
EVIDENCE: pyproject.toml, Makefile, .github/workflows/ci.yml, LICENSE, README.md, src/agentmaxxing/, tests/test_cli_help.py, uv.lock
NUMBERS: none claimed
DEVIATIONS: HANDOFF.md and CLAUDE.md are committed with M0 so the spec travels with the repo. `make demo` and `make study` exist but exit 1 with "not implemented" until M5/M4. uv was not installed; installed via `pip install uv` into Python 3.12.
KNOWN GAPS: CI has never run. `make` is not installed on this Windows machine, so the Makefile targets were not executed; the equivalent `uv run` commands were.
NEEDS MUFEED: push when ready, then confirm CI is green on GitHub.
```

## M1 Receipts

```
MILESTONE: M1 Receipts
STATUS: done
COMMIT: 8d67d15 M1: signed, hash-chained receipts, keygen and verify with tamper-detection tests
TESTS: 24/24, `uv run pytest --cov=agentmaxxing`, 93% line coverage (254 statements, 19 missed)
CI: not run (nothing pushed)
EVIDENCE: src/agentmaxxing/{receipts,store,keys,verify,cli}.py, tests/test_receipts.py, docs/receipts.md, .gitattributes
NUMBERS: 24 tests and 93% coverage, both from the pytest run above (not stored under results/; reproduce with the command). ruff check/format and `mypy --strict` on src: clean.
DEVIATIONS: Added `--expect-head` to `verify` (not in the spec) because removal of whole receipts from the end of a log is otherwise undetectable. Added .gitattributes (eol=lf) so the Makefile and workflow keep LF endings on Windows. Receipt stores redacted args/result plus SHA-256 over the raw values.
KNOWN GAPS: Tail removal is only caught if the caller pins the head hash. The private-key holder can forge a whole log. Redaction matches key names only, not secrets inside free text. Single-process writer only (no cross-process file lock). Uncovered lines are mostly defensive schema-error branches in verify.py and store.py.
NEEDS MUFEED: push when ready and confirm CI is green. Say "continue" for M2.
```

## M2 MCP stdio proxy

```
MILESTONE: M2 MCP stdio proxy
STATUS: partial (code and automated tests done; the manual Claude Desktop run is Mufeed's and has not happened)
COMMIT: see `git log -1` (commit message: "M2: MCP stdio proxy with per-call receipts and integration tests")
TESTS: 36/36, `uv run pytest` (12 new in tests/test_proxy.py, 24 from M0/M1). Coverage not reported: the proxy runs in a subprocess, which pytest-cov does not measure here. Full suite run 4 times, no flakes seen. ruff check, ruff format --check, `mypy --strict` on src: clean.
CI: not run (nothing pushed)
EVIDENCE: src/agentmaxxing/proxy.py, src/agentmaxxing/cli.py (proxy command), tests/test_proxy.py, tests/support/{mock_server,raw_upstream}.py, docs/claude-desktop.md
NUMBERS: 36 tests (pytest run above); 3,000,000-character payload used in the large-payload test; no results/ files, no measured claims in the README.
DEVIATIONS: (1) Installed mcp resolved to 2.3.0, where FastMCP is now `mcp.server.mcpserver.MCPServer`; the mock server uses that. (2) Large payloads are forwarded whole, but the stored copy in the log is replaced by a marker above `--max-stored-bytes` (default 262144); result_sha256 stays exact. This changed receipts.py and store.py (new optional argument, M1 behaviour unchanged by default). (3) When the upstream exits non-zero on its own, open calls are recorded as `error` even if the client had also hung up. (4) When the SDK server loses stdin mid-call it replies with a JSON-RPC "Connection closed" error; that is recorded as `error`, because it is what the upstream said.
KNOWN GAPS: Not tested against a real Claude Desktop or a non-Python upstream. Only the `tools/call` + `notifications/cancelled` flow is tracked; a response with a null id is ignored. JSON-RPC batches are observed but the tests do not exercise them. Reused in-flight ids are handled in code but untested. A call the client never cancels and the upstream never answers (while both stay alive) stays open and gets no receipt until shutdown. Receipts are written when a call completes, so receipt order is completion order, not request order.
NEEDS MUFEED: Manual run, exact steps in docs/claude-desktop.md: (1) `uv run agentmaxxing keygen --out <dir>\agent`; (2) wrap one MCP server in %APPDATA%\Claude\claude_desktop_config.json as shown there; (3) fully restart Claude Desktop; (4) ask it to use a tool of that server; (5) run `uv run agentmaxxing verify <log> --pubkey <dir>\agent.pub` and expect "OK: N receipts verified"; (6) edit one character in a copy of the log and confirm verify reports INVALID at the right line. Tell me the result. Also push and confirm CI. Say "continue" for M3.
```

## M3 Claim verification

```
MILESTONE: M3 Claim verification
STATUS: partial (everything built and measured; the 20-example human label review is outstanding)
COMMIT: see `git log -1` (commit message: "M3: claim verification, two extractors, 110 hand labels and a measured extractor evaluation")
TESTS: 64/64, `uv run pytest` (28 new: tests/test_claims.py 22, tests/test_check_cli.py 6). Coverage not measured this milestone. ruff check, ruff format, mypy --strict on src: clean.
CI: not run (nothing pushed)
EVIDENCE: src/agentmaxxing/{claims,extractor_eval,llm}.py, `agentmaxxing check` in cli.py, data/labels/examples.jsonl, docs/labelling.md, docs/label_review.md, scripts/{eval_extractor,replay_extractor_eval,render_extractor_table,make_review_sample}.py, results/extractor_eval.json, results/extractor_raw.jsonl, results/extractor_confusion.json
NUMBERS (all from results/extractor_eval.json unless noted; the README table is generated from it):
 - 110 examples, 113 gold claims (43 VERIFIED, 20 NOT_CALLED, 20 FAILED_REPORTED_AS_SUCCESS, 20 RESULT_MISREPORTED, 10 UNVERIFIABLE), 120 predicted claims, 0 extraction failures
 - precision/recall: VERIFIED 90%/21%, NOT_CALLED 30%/50%, FAILED_REPORTED_AS_SUCCESS 91%/50%, RESULT_MISREPORTED 28%/45%, UNVERIFIABLE 18%/60%
 - claim detection (paired by tool name): precision 57%, recall 60%
 - run: deepseek-r1:latest via Ollama 0.6.5, temperature 0, seed 0, 2026-11-24, 1024.5 s total
 - confusion matrix: results/extractor_confusion.json, recomputed from the raw replies by scripts/replay_extractor_eval.py, which checks it reproduces the stored metrics
DEVIATIONS: (1) Labels are written by Claude, not scraped from real agent runs, and not yet reviewed by a human. (2) Only a local Ollama model was used: no API keys were available, and Ollama had one model installed. (3) The eval ran once; the prompt was not tuned on these labels. (4) `check` requires --pubkey and refuses to check against a log that fails verification (not in the spec). (5) A label cross-check test caught a verifier bug (failure claims quoting details were flagged unchecked); the verifier was fixed, not the label.
KNOWN GAPS: The NL extractor is weak: 22 of 43 correct answers are flagged RESULT_MISREPORTED (the model writes phrases, not literal values, as facts), and it adds claims the labels lack. The headline numbers measure a small local reasoning model plus a strict verifier, not the best achievable pipeline. No held-out set. One annotator. Rounding is not forgiven. Structured extractor is tested on synthetic transcripts only. The 28 "extra" UNVERIFIABLE and 23 extra NOT_CALLED claims were not individually inspected.
NEEDS MUFEED: Review docs/label_review.md (20 examples, tick agree or write corrections) and tell me the result; I will fix any label and re-run `scripts/replay_extractor_eval.py` (no model needed). Decide whether M4 should use a stronger model than the local deepseek-r1 for the study (free API keys in .env would let us). Push and confirm CI. Say "continue" for M4.
```
