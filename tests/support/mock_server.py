"""Mock stdio MCP server built with the official ``mcp`` SDK, used by the proxy tests."""

from __future__ import annotations

import asyncio
import os

from mcp.server.mcpserver import MCPServer

server = MCPServer("mock")


@server.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@server.tool()
async def slow(seconds: float, label: str) -> str:
    """Sleep, then return the label (used to interleave concurrent calls)."""
    await asyncio.sleep(seconds)
    return label


@server.tool()
def fail() -> str:
    """Always raises, so the SDK returns an isError result."""
    raise RuntimeError("boom")


@server.tool()
def big(size: int) -> str:
    """Return a string of ``size`` characters."""
    return "x" * size


@server.tool()
def crash() -> str:
    """Kill the whole server process mid-call."""
    os._exit(3)


@server.tool()
def secret_echo(api_key: str) -> str:
    """Takes a secret-looking argument."""
    return "ok"


if __name__ == "__main__":
    server.run("stdio")
