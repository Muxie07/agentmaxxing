"""M0 acceptance: the CLI entry point exists and `--help` works."""

import subprocess
import sys

import pytest

from agentmaxxing.cli import build_parser


def test_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--help"])
    assert exc.value.code == 0
    assert "keygen" in capsys.readouterr().out


def test_module_runs_as_script() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "agentmaxxing.cli", "--help"], capture_output=True, text=True
    )
    assert proc.returncode == 0
    assert "verify" in proc.stdout
