# Handoff to Claude Code: build `agentmaxxing` (tool-call receipts + misreporting study)

Repo: https://github.com/Muxie07/agentmaxxing (currently empty, branch `main`)
Owner: Mufeed (B.Tech AI & DS graduate). This is a portfolio project for AI-startup roles.
Goal: show deep, verified engineering on one real AI-agent problem. It does not need to be novel. It must work, be measured, and be honest.

## How to work (read first)

- This file is the full specification. Work through it **autonomously**. Do not ask Mufeed which task to do: the next task is always the next unfinished milestone.
- Ask a question only when truly blocked: a missing API key, a manual step only he can do, or a contradiction in this file. Otherwise pick the most reasonable option, note it under DEVIATIONS, and keep going.
- One milestone per session unless told otherwise. Finish it completely (code, tests, CI, commit), then send the handback report and stop.
- This repo is `agentmaxxing`. It is **not** AURA. Ignore any AURA files, handovers or memories from other folders.

## The problem

AI agents often report tool results that never happened: a call that failed is reported as a success, a call that never ran is described, or real output is misquoted. `agentmaxxing` records a signed, tamper-evident receipt for every real tool call. It then checks the agent's final answer against those receipts and measures how often real models misreport under controlled faults.

## Prior art (read, credit, do not copy)

- `moshe-ship/toolproof` (MIT, last commit 2026-06-01, about 6k lines). It already does HMAC receipts, an HTTP proxy, SDK patching, a verifier with VERIFIED / UNVERIFIED / TAMPERED verdicts, and a trust score. Its README quotes a 91.1% hallucination figure from outside work; it does not publish its own measured study.
- `sumankrsh/mcp-gatekeeper` (MIT): a stdio MCP proxy plus a hash-chained audit log with an optional HMAC key. Good reference for the proxy loop.
- `darshansatpathy/agent-guardrails-gateway` (MIT): a YAML attack-scenario suite run in CI. Good reference for how evals are structured.

The README must have a "Prior art and what's different" section naming these three. Do not copy code. If any idea is adapted, say so in the README.

## What's different here (the reason this exists)

1. **A measured study.** How often do real models misreport tool outcomes, by fault type, with raw transcripts published. This is the headline.
2. **Measured claim extraction.** Claims are pulled from natural-language final answers. The extractor's precision and recall are reported against a hand-labelled set.
3. **Publicly verifiable receipts.** Ed25519 signatures plus a hash chain, so anyone holding the public key can verify a log. No shared secret is needed.
4. **MCP-native stdio proxy.** It works with Claude Desktop and any stdio MCP server, with no change to the agent.

## Hard rules

- Python 3.12, `uv`, `ruff`, `mypy --strict` on `src/`, `pytest`. GitHub Actions CI runs lint, types and tests on every push.
- **No fabricated numbers anywhere.** Every number in the README must be produced by a committed script. Its output file is committed under `results/`, and the README links to it.
- Use only free model access: Gemini API free tier, Groq free tier, OpenRouter free models, or local Ollama. Keys are read from `.env`. Commit `.env.example` only. Never commit or print keys.
- Use deterministic seeds wherever possible. Every model run records model id, date, temperature and run index.
- Do not `git push` and do not force-push. Commit once per milestone with a clear message. Mufeed pushes himself.
- If a milestone can't meet its acceptance criteria, stop and report. Don't weaken tests or skip checks to get green.
- Keep scope tight. Build no web dashboard unless every milestone is done.

## Milestones and acceptance criteria

### M0: Scaffold
- `src/agentmaxxing/`, `tests/`, `results/`, `docs/`, `pyproject.toml`, `Makefile` (`make test`, `make lint`, `make demo`, `make study`), CI workflow, MIT license, a README skeleton.
- Done when: CI is green on an empty test, and `uv run agentmaxxing --help` works.

### M1: Receipts
- Receipt fields: id, timestamp, server, tool, `args_sha256`, `result_sha256`, status (ok / error / timeout / cancelled), duration_ms, prev_hash, hash, Ed25519 signature. Hash over canonical JSON (sorted keys, no spaces). Store redacted args and results, scrubbing secret-looking keys.
- Append-only JSONL store. `agentmaxxing keygen`, `agentmaxxing verify <log> --pubkey <key>`.
- Done when tests prove that `verify` detects: an edited field, a deleted line, reordered lines, an inserted forged line, a wrong key, and a truncated file. Each case reports the first bad line number.

### M2: MCP stdio proxy
- `agentmaxxing proxy -- <upstream command>` wraps any stdio MCP server. It records one receipt per `tools/call` (request plus response, or error) and passes everything else through untouched.
- Must handle: concurrent requests with interleaved ids, `notifications/cancelled`, upstream crash, malformed JSON from either side, and large payloads.
- Integration tests use a mock MCP server built with the official `mcp` Python SDK. Add `docs/claude-desktop.md` with a working config example.
- Done when: integration tests pass, and a manual run through Claude Desktop produces a verifiable log. Mufeed does the manual run. Give him exact steps.

### M3: Claim verification
- Input: the agent's final answer plus the receipt log.
- Two extractors: (a) structured, from transcript tool-use blocks; (b) natural-language, LLM-based, with a JSON schema output.
- Verdicts: `VERIFIED`, `NOT_CALLED` (claimed but no receipt), `FAILED_REPORTED_AS_SUCCESS`, `RESULT_MISREPORTED` (receipt exists but the claimed facts contradict it), `UNVERIFIABLE`.
- Hand-label a set of at least 100 answer-and-claim examples in `data/labels/`, with a short labelling guide in `docs/labelling.md`. Mufeed reviews a sample of 20 and confirms.
- Done when: `results/extractor_eval.json` reports precision and recall per verdict for the NL extractor, and the README states these honestly, including where it's weak.

### M4: The misreporting study (headline)
- About 30 tasks across 5 to 6 mock tools (search, read_file, db_query, send_email, http_get, calculator).
- Fault injection per call: none, error, timeout, empty result, partial result, plausible-but-wrong result. Same seed across models.
- At least 2 free models, 3 runs per task-and-fault combination. Store every transcript and receipt log under `results/study/<model>/<run>/`.
- Report per model and fault type: misreport rate with 95% Wilson intervals, plus a breakdown by verdict. Also report cost and latency.
- Done when: `make study` reproduces `results/study_summary.json` and one chart (`results/study_chart.png`). The README table is generated from the JSON, not typed by hand. Write a "Threats to validity" paragraph covering small sample, mock tools, extractor error and free-tier model versions.

### M5: Demo and README
- `make demo` runs end to end in under 2 minutes, offline except for model calls. It shows a failed tool call being reported as success, and `agentmaxxing check` flagging it.
- README order: one-paragraph problem; 90-second demo GIF or video link (placeholder until Mufeed records it); results table; architecture diagram (Mermaid); quickstart; how verification works; prior art; limitations; how to reproduce.
- Write `docs/video-script.md`, a 90-second screen-recording script for Mufeed.

## Handback report (required at the end of each milestone)

Reply in this exact shape so it can be pasted back for review:

```
MILESTONE: M<n> <name>
STATUS: done | partial | blocked
COMMIT: <hash> <message>
TESTS: <passed>/<total>, <command used>, <coverage if measured>
CI: green | red | not run
EVIDENCE: <files produced, with paths>
NUMBERS: <every number claimed, with the file it comes from>
DEVIATIONS: <anything done differently from this handoff, and why>
KNOWN GAPS: <what is weak or untested>
NEEDS MUFEED: <manual steps, keys, decisions>
```

Stop after each milestone and wait for Mufeed to say "continue".
