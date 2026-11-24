"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .keys import KeyFileError, generate, load_public
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    code: int = args.func(args)
    return code


if __name__ == "__main__":
    sys.exit(main())
