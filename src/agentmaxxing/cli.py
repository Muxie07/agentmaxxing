"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .claims import (
    Claim,
    Verdict,
    extract_nl,
    extract_structured,
    verify_claims,
)
from .keys import KeyFileError, generate, load_private, load_public
from .llm import DEFAULT_HOST, OllamaClient, OllamaError
from .proxy import Proxy
from .store import ReceiptLog
from .verify import verify_log


def _cmd_keygen(args: argparse.Namespace) -> int:
    try:
        key_path, pub_path = generate(Path(args.out), force=args.force)
    except FileExistsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"private key: {key_path}  (keep secret; never commit)")
    print(f"public key:  {pub_path}  (share this to let others verify your logs)")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    try:
        public_key = load_public(Path(args.pubkey))
    except KeyFileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    result = verify_log(Path(args.log), public_key, expect_head=args.expect_head)
    print(result)
    return 0 if result.ok else 1


def _cmd_proxy(args: argparse.Namespace) -> int:
    command: list[str] = args.upstream
    try:
        private_key = load_private(Path(args.key))
        log = ReceiptLog(Path(args.log), private_key, max_stored_bytes=args.max_stored_bytes)
    except (KeyFileError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    name = args.server_name or Path(command[0]).stem
    print(f"agentmaxxing proxy: recording '{name}' to {args.log}", file=sys.stderr)
    proxy = Proxy(
        command,
        log,
        server_name=name,
        client_in=sys.stdin.buffer,
        client_out=sys.stdout.buffer,
        client_err=sys.stderr.buffer,
    )
    return proxy.run()


def _cmd_check(args: argparse.Namespace) -> int:
    if not args.answer and not args.transcript:
        print("error: give --answer and/or --transcript", file=sys.stderr)
        return 2
    try:
        public_key = load_public(Path(args.pubkey))
    except KeyFileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    log_path = Path(args.log)
    verified = verify_log(log_path, public_key, expect_head=args.expect_head)
    if not verified.ok:
        print(f"error: receipt log is not trustworthy: {verified}", file=sys.stderr)
        return 2
    receipts = [json.loads(ln) for ln in log_path.read_text(encoding="utf-8").splitlines() if ln]
    claims: list[Claim] = []
    try:
        if args.transcript:
            claims += extract_structured(json.loads(Path(args.transcript).read_text("utf-8")))
        if args.answer:
            tools = args.tools.split(",") if args.tools else sorted({r["tool"] for r in receipts})
            llm = OllamaClient(args.model, host=args.host)
            claims += extract_nl(Path(args.answer).read_text("utf-8"), tools, llm)
    except (OSError, ValueError, OllamaError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    results = verify_claims(claims, receipts)
    bad = [r for r in results if r.verdict is not Verdict.VERIFIED]
    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        print(f"log OK: {verified.receipts} receipts verified")
        for r in results:
            who = r.claim.tool or "<unnamed tool>"
            print(f"  {r.verdict.value:<28} {who}: {r.reason}")
        if not results:
            print("  no tool claims found in the answer")
    return 1 if bad else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentmaxxing",
        description="Signed, tamper-evident receipts for agent tool calls.",
    )
    parser.add_argument("--version", action="version", version=f"agentmaxxing {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    keygen = sub.add_parser("keygen", help="generate an Ed25519 keypair")
    keygen.add_argument("--out", default="agentmaxxing", help="path prefix for .key and .pub")
    keygen.add_argument("--force", action="store_true", help="overwrite existing key files")
    keygen.set_defaults(func=_cmd_keygen)

    verify = sub.add_parser("verify", help="verify a receipt log with a public key")
    verify.add_argument("log", help="path to the JSONL receipt log")
    verify.add_argument("--pubkey", required=True, help="path to the .pub file")
    verify.add_argument(
        "--expect-head",
        help="last known-good receipt hash; also detects removal of receipts from the end",
    )
    verify.set_defaults(func=_cmd_verify)

    proxy = sub.add_parser(
        "proxy",
        help="wrap a stdio MCP server and record a receipt per tools/call",
        description="Usage: agentmaxxing proxy [options] -- <upstream command> [args...]",
    )
    proxy.add_argument("--key", default="agentmaxxing.key", help="private key file (.key)")
    proxy.add_argument("--log", default="agentmaxxing.receipts.jsonl", help="receipt log path")
    proxy.add_argument("--server-name", help="name stored in receipts (default: command name)")
    proxy.add_argument(
        "--max-stored-bytes",
        type=int,
        default=262144,
        help="store a marker instead of args/results larger than this (hashes stay exact)",
    )
    proxy.add_argument("upstream", nargs="+", help="upstream MCP server command (after --)")
    proxy.set_defaults(func=_cmd_proxy)

    check = sub.add_parser(
        "check",
        help="check an agent's final answer against a verified receipt log",
        description=(
            "Exit 0 if every claim is VERIFIED, 1 if any claim is not, 2 on bad input or an "
            "untrustworthy log. Natural-language extraction uses a local Ollama model and is "
            "imperfect; see results/extractor_eval.json for measured precision and recall."
        ),
    )
    check.add_argument("--log", required=True, help="receipt log (JSONL)")
    check.add_argument("--pubkey", required=True, help="public key; the log is verified first")
    check.add_argument("--answer", help="text file with the agent's final answer")
    check.add_argument("--transcript", help="JSON transcript with tool_use/tool_result blocks")
    check.add_argument("--tools", help="comma-separated tool names the agent had (default: log)")
    check.add_argument("--model", default="deepseek-r1:latest", help="Ollama model for --answer")
    check.add_argument("--host", default=DEFAULT_HOST, help="Ollama host")
    check.add_argument("--expect-head", help="last known-good receipt hash (see verify)")
    check.add_argument("--json", action="store_true", help="print results as JSON")
    check.set_defaults(func=_cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    code: int = args.func(args)
    return code


if __name__ == "__main__":
    sys.exit(main())
