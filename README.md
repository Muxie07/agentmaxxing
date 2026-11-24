# agentmaxxing

Signed, tamper-evident receipts for every real tool call an AI agent makes, a verifier that
checks an agent's final answer against those receipts, and a measured study of how often real
models misreport tool outcomes.

> Status: under construction. Milestones M0 (scaffold), M1 (receipts) and M2 (MCP stdio proxy) are in place.
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

## Prior art and what's different

To be written in M5. It will credit `moshe-ship/toolproof`, `sumankrsh/mcp-gatekeeper` and
`darshansatpathy/agent-guardrails-gateway`.
