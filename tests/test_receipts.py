"""M1 acceptance tests: receipts are well-formed and `verify` catches every tamper case."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agentmaxxing import keys
from agentmaxxing.cli import main
from agentmaxxing.receipts import GENESIS_HASH, canonical_json, make_receipt, redact, sha256_hex
from agentmaxxing.store import ReceiptLog
from agentmaxxing.verify import verify_log

N = 5  # receipts in the standard fixture log


@pytest.fixture
def key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


@pytest.fixture
def log_path(tmp_path: Path, key: Ed25519PrivateKey) -> Path:
    path = tmp_path / "calls.jsonl"
    log = ReceiptLog(path, key)
    statuses = ["ok", "error", "timeout", "cancelled", "ok"]
    for i, status in enumerate(statuses):
        log.append(
            server="files",
            tool=f"tool_{i}",
            args={"n": i, "api_key": "sk-secret"},
            result={"echo": i},
            status=status,  # type: ignore[arg-type]
            duration_ms=10 + i,
        )
    return path


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


# ---------- format ----------


def test_valid_log_verifies(log_path: Path, key: Ed25519PrivateKey) -> None:
    result = verify_log(log_path, key.public_key())
    assert result.ok
    assert result.receipts == N
    assert result.bad_line is None


def test_empty_log_verifies(tmp_path: Path, key: Ed25519PrivateKey) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("")
    assert verify_log(path, key.public_key()).ok


def test_receipt_has_required_fields_and_chain(log_path: Path) -> None:
    recs = [json.loads(line) for line in read_lines(log_path)]
    expected = {
        "id", "timestamp", "server", "tool", "args", "result", "args_sha256",
        "result_sha256", "status", "duration_ms", "prev_hash", "hash", "signature",
    }  # fmt: skip
    for rec in recs:
        assert set(rec) == expected
    assert recs[0]["prev_hash"] == GENESIS_HASH
    for prev, cur in zip(recs, recs[1:], strict=False):
        assert cur["prev_hash"] == prev["hash"]
    assert [r["status"] for r in recs] == ["ok", "error", "timeout", "cancelled", "ok"]


def test_canonical_json_is_sorted_and_compact() -> None:
    assert canonical_json({"b": 1, "a": [1, 2]}) == '{"a":[1,2],"b":1}'


def test_redaction_scrubs_secret_keys_but_hash_covers_raw(key: Ed25519PrivateKey) -> None:
    args = {"query": "hi", "headers": {"Authorization": "Bearer abc"}, "api_key": "k"}
    receipt = make_receipt(
        private_key=key, server="s", tool="t", args=args, result={"ok": True},
        status="ok", duration_ms=1, prev_hash=GENESIS_HASH,
    )  # fmt: skip
    stored = receipt.data["args"]
    assert stored["api_key"] == "[REDACTED]"
    assert stored["headers"]["Authorization"] == "[REDACTED]"
    assert stored["query"] == "hi"
    assert "Bearer abc" not in receipt.to_line()
    # args_sha256 is over the raw args, so the original data can be proven against it.
    assert receipt.data["args_sha256"] == sha256_hex(canonical_json(args))


def test_redact_handles_nested_lists() -> None:
    assert redact([{"password": "x", "ok": 1}]) == [{"password": "[REDACTED]", "ok": 1}]


def test_resume_continues_the_chain(log_path: Path, key: Ed25519PrivateKey) -> None:
    log = ReceiptLog(log_path, key)
    log.append(server="s", tool="more", args={}, result=None, status="ok", duration_ms=1)
    result = verify_log(log_path, key.public_key())
    assert result.ok
    assert result.receipts == N + 1


# ---------- tamper detection: each case must report the first bad line ----------


def test_detects_edited_field(log_path: Path, key: Ed25519PrivateKey) -> None:
    lines = read_lines(log_path)
    rec = json.loads(lines[2])
    rec["status"] = "ok"  # was "timeout"; a failure rewritten as success
    lines[2] = canonical_json(rec)
    write_lines(log_path, lines)
    result = verify_log(log_path, key.public_key())
    assert not result.ok
    assert result.bad_line == 3
    assert "hash mismatch" in result.reason


def test_detects_edited_field_even_if_hash_is_recomputed(
    log_path: Path, key: Ed25519PrivateKey
) -> None:
    """An attacker who fixes the hash but lacks the private key still fails the signature."""
    from agentmaxxing.receipts import compute_hash

    lines = read_lines(log_path)
    rec = json.loads(lines[1])
    rec["result"] = {"echo": "forged"}
    rec["hash"] = compute_hash(rec)
    lines[1] = canonical_json(rec)
    write_lines(log_path, lines)
    result = verify_log(log_path, key.public_key())
    assert not result.ok
    # Line 2's own signature breaks first (the chain then also breaks at line 3).
    assert result.bad_line == 2
    assert "signature" in result.reason


def test_detects_deleted_line(log_path: Path, key: Ed25519PrivateKey) -> None:
    lines = read_lines(log_path)
    del lines[1]  # remove receipt 2
    write_lines(log_path, lines)
    result = verify_log(log_path, key.public_key())
    assert not result.ok
    assert result.bad_line == 2  # the receipt that now follows the gap
    assert "prev_hash" in result.reason


def test_detects_reordered_lines(log_path: Path, key: Ed25519PrivateKey) -> None:
    lines = read_lines(log_path)
    lines[2], lines[3] = lines[3], lines[2]
    write_lines(log_path, lines)
    result = verify_log(log_path, key.public_key())
    assert not result.ok
    assert result.bad_line == 3
    assert "prev_hash" in result.reason


def test_detects_inserted_forged_line_unsigned_chain(
    log_path: Path, key: Ed25519PrivateKey
) -> None:
    """Forger copies a real receipt's shape, fixes its prev_hash/hash, signs with their own key."""
    attacker = Ed25519PrivateKey.generate()
    lines = read_lines(log_path)
    prev = json.loads(lines[1])["hash"]
    forged = make_receipt(
        private_key=attacker, server="files", tool="send_email", args={"to": "x"},
        result={"sent": True}, status="ok", duration_ms=5, prev_hash=prev,
    )  # fmt: skip
    lines.insert(2, forged.to_line())
    write_lines(log_path, lines)
    result = verify_log(log_path, key.public_key())
    assert not result.ok
    assert result.bad_line == 3
    assert "signature" in result.reason


def test_detects_inserted_line_with_correct_chain_but_bad_link_after(
    log_path: Path, key: Ed25519PrivateKey
) -> None:
    """Even a perfectly signed insert breaks the *next* receipt's prev_hash."""
    lines = read_lines(log_path)
    prev = json.loads(lines[1])["hash"]
    inserted = make_receipt(
        private_key=key, server="files", tool="extra", args={}, result={},
        status="ok", duration_ms=1, prev_hash=prev,
    )  # fmt: skip
    lines.insert(2, inserted.to_line())
    write_lines(log_path, lines)
    result = verify_log(log_path, key.public_key())
    assert not result.ok
    assert result.bad_line == 4  # original receipt 3 no longer links to its predecessor
    assert "prev_hash" in result.reason


def test_detects_wrong_key(log_path: Path) -> None:
    other = Ed25519PrivateKey.generate().public_key()
    result = verify_log(log_path, other)
    assert not result.ok
    assert result.bad_line == 1
    assert "signature" in result.reason


def test_detects_truncated_file_mid_line(log_path: Path, key: Ed25519PrivateKey) -> None:
    raw = log_path.read_bytes()
    log_path.write_bytes(raw[: len(raw) - 40])  # cut inside the last receipt
    result = verify_log(log_path, key.public_key())
    assert not result.ok
    assert result.bad_line == N
    assert "truncated" in result.reason


def test_detects_truncation_in_the_middle_of_a_middle_line(
    log_path: Path, key: Ed25519PrivateKey
) -> None:
    lines = read_lines(log_path)
    lines[2] = lines[2][:50]
    write_lines(log_path, lines)
    result = verify_log(log_path, key.public_key())
    assert not result.ok
    assert result.bad_line == 3
    assert "not valid JSON" in result.reason


def test_tail_removal_needs_expect_head(log_path: Path, key: Ed25519PrivateKey) -> None:
    """Documented limit: dropping whole receipts from the end is invisible without a pinned head."""
    full = verify_log(log_path, key.public_key())
    lines = read_lines(log_path)
    write_lines(log_path, lines[:3])
    without_pin = verify_log(log_path, key.public_key())
    assert without_pin.ok  # honest limitation, not a bug
    with_pin = verify_log(log_path, key.public_key(), expect_head=full.head)
    assert not with_pin.ok
    assert with_pin.bad_line == 4
    assert "removed from the end" in with_pin.reason


def test_detects_blank_line_and_missing_field(log_path: Path, key: Ed25519PrivateKey) -> None:
    lines = read_lines(log_path)
    rec = json.loads(lines[3])
    del rec["signature"]
    lines[3] = canonical_json(rec)
    write_lines(log_path, lines)
    result = verify_log(log_path, key.public_key())
    assert not result.ok
    assert result.bad_line == 4
    assert "missing fields" in result.reason


def test_missing_log_file(tmp_path: Path, key: Ed25519PrivateKey) -> None:
    result = verify_log(tmp_path / "nope.jsonl", key.public_key())
    assert not result.ok


# ---------- CLI ----------


def test_cli_keygen_and_verify_roundtrip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    prefix = tmp_path / "keys" / "agent"
    assert main(["keygen", "--out", str(prefix)]) == 0
    key_path, pub_path = prefix.with_suffix(".key"), prefix.with_suffix(".pub")
    assert key_path.exists() and pub_path.exists()

    log = ReceiptLog(tmp_path / "calls.jsonl", keys.load_private(key_path))
    log.append(server="s", tool="t", args={"a": 1}, result={"b": 2}, status="ok", duration_ms=3)

    assert main(["verify", str(tmp_path / "calls.jsonl"), "--pubkey", str(pub_path)]) == 0
    assert "OK: 1 receipts" in capsys.readouterr().out

    # tamper, then expect exit code 1 and the line number
    text = (tmp_path / "calls.jsonl").read_text().replace('"ok"', '"error"')
    (tmp_path / "calls.jsonl").write_text(text)
    assert main(["verify", str(tmp_path / "calls.jsonl"), "--pubkey", str(pub_path)]) == 1
    assert "line 1" in capsys.readouterr().out


def test_cli_keygen_refuses_to_overwrite(tmp_path: Path) -> None:
    prefix = tmp_path / "agent"
    assert main(["keygen", "--out", str(prefix)]) == 0
    assert main(["keygen", "--out", str(prefix)]) == 2
    assert main(["keygen", "--out", str(prefix), "--force"]) == 0


def test_cli_verify_bad_pubkey(tmp_path: Path) -> None:
    bad = tmp_path / "bad.pub"
    bad.write_text("not hex")
    (tmp_path / "x.jsonl").write_text("")
    assert main(["verify", str(tmp_path / "x.jsonl"), "--pubkey", str(bad)]) == 2
