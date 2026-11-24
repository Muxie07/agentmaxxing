# Using the proxy with Claude Desktop

`agentmaxxing proxy` sits between Claude Desktop and any stdio MCP server. It forwards every
line unchanged and writes one signed receipt per `tools/call`. The agent needs no changes.

```
Claude Desktop  <->  agentmaxxing proxy  <->  your MCP server
                          |
                          +--> agentmaxxing.receipts.jsonl (signed, hash-chained)
```

## 1. Create a key pair (once)

```
uv run agentmaxxing keygen --out C:\Users\<you>\agentmaxxing-keys\agent
```

This writes `agent.key` (private; the proxy signs with it) and `agent.pub` (share this to let
anyone verify).

## 2. Edit the Claude Desktop config

Open `%APPDATA%\Claude\claude_desktop_config.json` (Settings > Developer > Edit Config) and
wrap the server you already use. Everything after `--` is your original command, unchanged.

Example: the reference filesystem server, wrapped.

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "uv",
      "args": [
        "--directory", "C:\\Users\\<you>\\path\\to\\agentmaxxing",
        "run", "agentmaxxing", "proxy",
        "--key", "C:\\Users\\<you>\\agentmaxxing-keys\\agent.key",
        "--log", "C:\\Users\\<you>\\agentmaxxing-logs\\filesystem.jsonl",
        "--server-name", "filesystem",
        "--",
        "npx", "-y", "@modelcontextprotocol/server-filesystem", "C:\\Users\\<you>\\Documents"
      ]
    }
  }
}
```

Use absolute paths for `--key` and `--log`: Claude Desktop does not start in your project
folder. Backslashes must be doubled in JSON. On macOS/Linux use normal paths.

Restart Claude Desktop fully (quit from the tray icon, then reopen).

## 3. Make some tool calls

Ask Claude something that uses the server, for example "list the files in my Documents folder
and read one of them". Each tool call appends a line to the log. Proxy diagnostics go to the
MCP log (`%APPDATA%\Claude\logs\mcp-server-filesystem.log`), never to the protocol stream.

## 4. Verify the log

```
uv run agentmaxxing verify C:\Users\<you>\agentmaxxing-logs\filesystem.jsonl --pubkey C:\Users\<you>\agentmaxxing-keys\agent.pub
```

Expected: an "ok" result with the receipt count. To see tampering detected, copy the log, edit a
character inside any line, and verify the copy: it names the first bad line number.

To also catch deletion of receipts from the **end** of a log, record the last receipt's `hash`
and pass it back later with `--expect-head <hash>`.

## Behaviour worth knowing

- Receipts store args and results with secret-looking key names redacted. Hashes cover the raw
  values. Values over `--max-stored-bytes` (default 256 KiB) are replaced by a marker in the
  log; the hash stays exact.
- The log is single-writer: give each wrapped server its own `--log`.
- If the upstream crashes or the client disconnects mid-call, open calls get a receipt
  (`error` or `cancelled`) with a `proxy_note` explaining why.
- If the proxy cannot start the upstream command it exits with code 127 and says so on stderr.
