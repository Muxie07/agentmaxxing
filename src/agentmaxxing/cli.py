"""Command-line entry point (M0 scaffold: no subcommands yet)."""

from __future__ import annotations

import argparse
import sys

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentmaxxing",
        description="Signed, tamper-evident receipts for agent tool calls.",
    )
    parser.add_argument("--version", action="version", version=f"agentmaxxing {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
