# Receipts

One receipt is written per real tool call, as one line of canonical JSON (sorted keys, no
spaces) in an append-only JSONL log.

| Field | Meaning |
|---|---|
| `id` | random UUID (hex) |
| `timestamp` | UTC, ISO 8601, millisecond precision |
| `server`, `tool` | which MCP server and tool were called |
| `args`, `result` | stored copies with secret-looking **keys** redacted |
| `args_sha256`, `result_sha256` | SHA-256 of the canonical JSON of the **raw, unredacted** values |
| `status` | `ok`, `error`, `timeout` or `cancelled` |
| `duration_ms` | wall-clock duration |
| `prev_hash` | `hash` of the previous receipt (64 zeros for the first) |
| `hash` | SHA-256 over all fields above except `hash` and `signature` |
| `signature` | Ed25519 signature (hex) over the ASCII bytes of `hash` |

Keys are 32 raw bytes stored as hex: `agentmaxxing keygen --out keys/agent` writes
`agent.key` (private, mode 0600) and `agent.pub`. Only the public key is needed to verify.

## What `agentmaxxing verify <log> --pubkey <key>` catches

Every case reports the first bad (1-based) line number. Each is covered by a test in
`tests/test_receipts.py`.

| Tampering | Reported at |
|---|---|
| a field edited | that line (hash mismatch, or signature if the hash was recomputed) |
| a line deleted | the line after the gap (`prev_hash` break) |
| lines reordered | the first out-of-order line |
| a forged line inserted (attacker key) | the inserted line (bad signature) |
| a validly signed line inserted | the line after it (`prev_hash` break) |
| wrong public key | line 1 |
| file cut mid-line | the incomplete line |

## What it does not catch

- **Removing receipts from the end of the log at a line boundary.** A shorter log is still a
  valid chain. Pin the expected head with `--expect-head <hash>` (printed by a successful
  verify) to detect it; store that hash somewhere the log writer cannot edit.
- **Whoever holds the private key can forge a whole log.** Receipts prove the log was
  produced by the key holder and not altered since, not that the tool call really happened.
- **Redaction looks at key names only.** A secret inside a free-text value is stored as is.
