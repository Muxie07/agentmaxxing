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
