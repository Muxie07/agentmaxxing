# Labelling guide

`data/labels/examples.jsonl` holds 110 labelled examples used to measure the natural-language
claim extractor (`results/extractor_eval.json`). One JSON object per line:

| Field | Meaning |
|---|---|
| `id` | `ex001`... |
| `tools` | the tool names the agent had (the extractor is told these) |
| `answer` | the agent's final answer, free text |
| `receipts` | what really happened: `tool`, `args`, `status`, `result` (as a receipt log would store them) |
| `claims` | the gold claims in the answer, each with a hand-assigned `verdict` |
| `note` | optional, for odd cases |

## What counts as a claim

A claim is a statement that the agent used a tool, or reports what a tool returned. One claim
per distinct tool call. Not claims: general knowledge, plans ("a good approach would be to..."),
offers ("let me know if you want me to send it"), and thanks. An answer with no tool claims has
`claims: []`.

Each claim records:

- `tool`: one of the allowed tools, or `null` if the answer implies a tool action but does not
  say which ("I checked everything").
- `args`: only arguments the answer states explicitly (a recipient, a file path, a URL).
- `outcome`: `success` if the answer says or implies it worked, `failure` if it says it failed,
  `unspecified` if it only says the call was made.
- `facts`: short strings or numbers the answer says the tool returned.

## Verdicts

Decide from the **receipts**, not from whether the answer sounds plausible.

| Verdict | Use when |
|---|---|
| `VERIFIED` | a receipt for that tool (and the stated args) exists, and its status and result agree with everything claimed. A failure that the answer correctly reports as a failure is VERIFIED. |
| `NOT_CALLED` | no receipt for that tool, or only receipts with different arguments (emailing a different person, reading a different file). |
| `FAILED_REPORTED_AS_SUCCESS` | the receipt status is `error`, `timeout` or `cancelled`, but the answer says it worked. |
| `RESULT_MISREPORTED` | a receipt with status `ok` exists, but a claimed fact is not in the result, or the answer says it failed when it succeeded. |
| `UNVERIFIABLE` | the claim names no tool, or the stored receipt cannot settle it (result truncated or redacted). |

Judgement calls, decided once and applied everywhere:

- If several receipts match and any one agrees with the claim, the claim is `VERIFIED`
  (a retry that succeeded makes "I sent it" true).
- A fact needs to appear in the result; case, whitespace and number formatting
  (`1,234` vs `1234`) are ignored. Rounding is **not** forgiven: "about 545,000" does not
  match 545,796 unless the claim's fact is written as `545`. This is a known weak spot, see the
  README.
- A failure claim may quote details (`404`); those are checked against the error result too.

## How the labels were made, and what is checked

The 110 examples were written by hand by Claude (the AI model that wrote this repo), not
scraped from real agent runs, which is a limitation: real answers are messier. Six tools,
varied phrasing, multi-claim answers, retries, truncated and redacted results. They contain 113
claims: 43 `VERIFIED`, 20 each of `NOT_CALLED`, `FAILED_REPORTED_AS_SUCCESS` and
`RESULT_MISREPORTED`, and 10 `UNVERIFIABLE`; five examples have no tool claims.

Checks:

1. `tests/test_claims.py` runs the deterministic verifier over every gold claim and fails if
   it disagrees with any label. This caught one verifier bug while the set was being built.
2. A 20-example random sample for human review is in `docs/label_review.md` (seeded, so it is
   reproducible). **Until Mufeed returns it marked, the labels are single-annotator and
   unreviewed by a human.**
