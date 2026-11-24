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
