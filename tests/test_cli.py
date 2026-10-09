"""Tests for PBOM CLI commands."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from pbom.cli import main
from pbom.emitter import PBOMEmitter

_SPECIAL_FILE_TIMEOUT_S = 10


def _runner() -> CliRunner:
    """Create CliRunner with exception wrapping disabled."""
    return CliRunner(catch_exceptions=False)


def test_init_creates_directory_and_config(tmp_path, monkeypatch) -> None:
    """pbom init should create .pbom and config.json with defaults."""
    monkeypatch.chdir(tmp_path)
    runner = _runner()

    result = runner.invoke(main, ["init"])

    assert result.exit_code == 0
    pbom_dir = tmp_path / ".pbom"
    config_path = pbom_dir / "config.json"
    assert pbom_dir.exists()
    assert config_path.exists()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["storage_mode"] == "fingerprint"
    assert payload["pbom_version"] == "1.0.0"


def test_init_appends_to_existing_gitignore(tmp_path, monkeypatch) -> None:
    """pbom init should append .pbom/ to existing .gitignore."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text("venv/\n__pycache__/\n", encoding="utf-8")
    runner = _runner()

    result = runner.invoke(main, ["init"])

    assert result.exit_code == 0
    content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "venv/" in content
    assert "__pycache__/" in content
    assert ".pbom/" in content.splitlines()


def test_init_does_not_duplicate_gitignore_entry(tmp_path, monkeypatch) -> None:
    """pbom init should not duplicate .pbom/ line if already present."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text("venv/\n.pbom/\n", encoding="utf-8")
    runner = _runner()

    result = runner.invoke(main, ["init"])

    assert result.exit_code == 0
    lines = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert lines.count(".pbom/") == 1


def test_init_does_not_create_gitignore_if_absent(tmp_path, monkeypatch) -> None:
    """pbom init should not create .gitignore when it does not exist."""
    monkeypatch.chdir(tmp_path)
    runner = _runner()

    result = runner.invoke(main, ["init"])

    assert result.exit_code == 0
    assert not (tmp_path / ".gitignore").exists()


def test_init_exit_code_and_output(tmp_path, monkeypatch) -> None:
    """pbom init should exit zero and print Initialized message."""
    monkeypatch.chdir(tmp_path)
    runner = _runner()

    result = runner.invoke(main, ["init"])

    assert result.exit_code == 0
    assert "Initialized" in result.output


def test_validate_on_valid_chain_exits_zero(tmp_path, monkeypatch) -> None:
    """pbom validate should PASS and exit 0 on intact chain."""
    monkeypatch.chdir(tmp_path)
    emitter = PBOMEmitter(
        application_id="test", output_dir=tmp_path / ".pbom", sdk_version="0.1.0"
    )
    with emitter.commit("sys", "user") as ctx:
        ctx.complete(model_id="openai/gpt-4o", response_text="resp")
    runner = _runner()

    result = runner.invoke(main, ["validate"])

    assert result.exit_code == 0
    assert "PASS" in result.output


def test_validate_on_empty_directory_exits_zero(tmp_path, monkeypatch) -> None:
    """Empty initialized chain should validate as PASS."""
    monkeypatch.chdir(tmp_path)
    runner = _runner()
    runner.invoke(main, ["init"])

    result = runner.invoke(main, ["validate"])

    assert result.exit_code == 0


def test_validate_on_broken_chain_exits_one(tmp_path, monkeypatch) -> None:
    """Tampered previous_entry_hash should make validate exit 1 with FAIL."""
    monkeypatch.chdir(tmp_path)
    emitter = PBOMEmitter(
        application_id="test", output_dir=tmp_path / ".pbom", sdk_version="0.1.0"
    )
    with emitter.commit("sys1", "user1") as ctx:
        ctx.complete(model_id="openai/gpt-4o", response_text="resp1")
    with emitter.commit("sys2", "user2") as ctx:
        ctx.complete(model_id="openai/gpt-4o", response_text="resp2")

    files = sorted((tmp_path / ".pbom").glob("*.pbom.json"))
    second = json.loads(files[1].read_text(encoding="utf-8"))
    second["identity"]["previous_entry_hash"] = "0" * 64
    files[1].write_text(
        json.dumps(second, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )

    runner = _runner()
    result = runner.invoke(main, ["validate"])

    assert result.exit_code == 1
    assert "FAIL" in result.output


def test_validate_missing_directory_exits_one(tmp_path, monkeypatch) -> None:
    """pbom validate should exit 1 when the target directory does not exist."""
    monkeypatch.chdir(tmp_path)
    runner = _runner()

    result = runner.invoke(main, ["validate", "missing-dir"])

    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_validate_accepts_explicit_directory_argument(tmp_path, monkeypatch) -> None:
    """pbom validate should work when directory path is explicitly provided."""
    monkeypatch.chdir(tmp_path)
    output_dir = tmp_path / "custom-pbom"
    emitter = PBOMEmitter(
        application_id="test", output_dir=output_dir, sdk_version="0.1.0"
    )
    with emitter.commit("sys", "user") as ctx:
        ctx.complete(model_id="openai/gpt-4o", response_text="resp")
    runner = _runner()

    result = runner.invoke(main, ["validate", str(output_dir)])

    assert result.exit_code == 0
    assert "PASS" in result.output


def test_validate_empty_directory_chain_links(tmp_path, monkeypatch) -> None:
    """Empty chain should report Chain links: 0/0 valid without first-record note."""
    monkeypatch.chdir(tmp_path)
    runner = _runner()
    runner.invoke(main, ["init"])

    result = runner.invoke(main, ["validate"])

    assert result.exit_code == 0
    assert "Chain links: 0/0 valid" in result.output
    assert "(first record" not in result.output


def test_validate_chain_links_includes_first_record_note(
    tmp_path, monkeypatch
) -> None:
    """N-record chain should report (N-1)/(N-1) valid with first-record note."""
    monkeypatch.chdir(tmp_path)
    _emit_n_records(tmp_path / ".pbom", 3)
    runner = _runner()

    result = runner.invoke(main, ["validate"])

    assert result.exit_code == 0
    assert (
        "Chain links: 2/2 valid (first record has no predecessor)" in result.output
    )


def test_validate_fingerprint_shows_unverifiable_note(
    tmp_path, monkeypatch
) -> None:
    """Fingerprint chain should print the unverifiable-commitments note."""
    monkeypatch.chdir(tmp_path)
    _emit_n_records(tmp_path / ".pbom", 1)
    runner = _runner()

    result = runner.invoke(main, ["validate"])

    assert result.exit_code == 0
    assert "unverifiable=" in result.output
    assert (
        "note: unverifiable commitments can't be recomputed from stored data"
        in result.output
    )


def test_status_shows_expected_fields(tmp_path, monkeypatch) -> None:
    """pbom status should print key informational status fields."""
    monkeypatch.chdir(tmp_path)
    emitter = PBOMEmitter(
        application_id="test", output_dir=tmp_path / ".pbom", sdk_version="0.1.0"
    )
    with emitter.commit("sys", "user") as ctx:
        ctx.complete(model_id="openai/gpt-4o", response_text="resp")
    runner = _runner()

    result = runner.invoke(main, ["status"])

    assert result.exit_code == 0
    assert "Record count:" in result.output
    assert "Chain health:" in result.output
    assert "Storage mode:" in result.output
    assert "Chain sequence range:" in result.output
    assert "Commitments:" in result.output


def test_status_on_empty_directory_shows_na(tmp_path, monkeypatch) -> None:
    """pbom status on empty initialized directory should show n/a values."""
    monkeypatch.chdir(tmp_path)
    runner = _runner()
    runner.invoke(main, ["init"])

    result = runner.invoke(main, ["status"])

    assert result.exit_code == 0
    assert "n/a" in result.output


def test_status_reports_broken_chain_health_and_unreadable_files(
    tmp_path, monkeypatch
) -> None:
    """pbom status should report broken health and unreadable file counts."""
    monkeypatch.chdir(tmp_path)
    output_dir = tmp_path / ".pbom"
    emitter = PBOMEmitter(
        application_id="test", output_dir=output_dir, sdk_version="0.1.0"
    )
    with emitter.commit("sys1", "user1") as ctx:
        ctx.complete(model_id="openai/gpt-4o", response_text="resp1")
    with emitter.commit("sys2", "user2") as ctx:
        ctx.complete(model_id="openai/gpt-4o", response_text="resp2")

    files = sorted(output_dir.glob("*.pbom.json"))
    second = json.loads(files[1].read_text(encoding="utf-8"))
    second["identity"]["previous_entry_hash"] = "0" * 64
    files[1].write_text(
        json.dumps(second, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "corrupt.pbom.json").write_text("not-json", encoding="utf-8")

    runner = _runner()
    result = runner.invoke(main, ["status"])

    assert result.exit_code == 0
    assert "Chain health: broken" in result.output
    assert "Unreadable files skipped: 1" in result.output


def test_export_schema_writes_file_and_outputs_path(tmp_path, monkeypatch) -> None:
    """pbom export-schema should create valid JSON schema file."""
    monkeypatch.chdir(tmp_path)
    runner = _runner()
    output_path = tmp_path / "nested" / "schema.json"

    result = runner.invoke(main, ["export-schema", str(output_path)])

    assert result.exit_code == 0
    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert "Schema written to" in result.output


def _emit_n_records(output_dir, count: int) -> None:
    """Emit ``count`` chained PBOM records into ``output_dir``."""
    emitter = PBOMEmitter(
        application_id="test", output_dir=output_dir, sdk_version="0.1.0"
    )
    for i in range(count):
        with emitter.commit(f"sys{i}", f"user{i}") as ctx:
            ctx.complete(model_id="openai/gpt-4o", response_text=f"resp{i}")


def test_records_missing_directory_exits_one(tmp_path, monkeypatch) -> None:
    """pbom records should exit 1 when the target directory does not exist."""
    monkeypatch.chdir(tmp_path)
    runner = _runner()

    result = runner.invoke(main, ["records", "missing-dir"])

    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_records_empty_directory_exits_zero(tmp_path, monkeypatch) -> None:
    """pbom records on an empty directory should exit 0 without crashing."""
    monkeypatch.chdir(tmp_path)
    runner = _runner()
    runner.invoke(main, ["init"])

    result = runner.invoke(main, ["records"])

    assert result.exit_code == 0
    assert "No records." in result.output


def test_records_last_n_returns_exactly_n_rows(tmp_path, monkeypatch) -> None:
    """pbom records --last N should show exactly N data rows when more exist."""
    monkeypatch.chdir(tmp_path)
    _emit_n_records(tmp_path / ".pbom", 5)
    runner = _runner()

    result = runner.invoke(main, ["records", "--last", "3"])

    assert result.exit_code == 0
    data_rows = [
        line
        for line in result.output.splitlines()
        if line and not line.startswith("SEQ") and not line.startswith("-")
    ]
    assert len(data_rows) == 3
    assert "3" in data_rows[0]
    assert "5" in data_rows[-1]


def test_records_record_found_shows_detail(tmp_path, monkeypatch) -> None:
    """pbom records --record SEQ should print a detail block for that record."""
    monkeypatch.chdir(tmp_path)
    _emit_n_records(tmp_path / ".pbom", 2)
    runner = _runner()

    result = runner.invoke(main, ["records", "--record", "1"])

    assert result.exit_code == 0
    assert "entry_id:" in result.output
    assert "created_at_iso:" in result.output
    assert "model_id:" in result.output
    assert "previous_entry_hash: n/a (first record)" in result.output


def test_records_record_not_found_exits_one(tmp_path, monkeypatch) -> None:
    """pbom records --record SEQ should exit 1 when the sequence is absent."""
    monkeypatch.chdir(tmp_path)
    _emit_n_records(tmp_path / ".pbom", 1)
    runner = _runner()

    result = runner.invoke(main, ["records", "--record", "99"])

    assert result.exit_code == 1
    assert "not found" in result.output


def test_records_format_json_parses_and_has_context(tmp_path, monkeypatch) -> None:
    """pbom records --format json should emit aliased JSON with @context."""
    monkeypatch.chdir(tmp_path)
    _emit_n_records(tmp_path / ".pbom", 1)
    runner = _runner()

    result = runner.invoke(main, ["records", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert "@context" in payload[0]


def test_records_skips_unreadable_files(tmp_path, monkeypatch) -> None:
    """Corrupt .pbom.json files should be counted and not crash records."""
    monkeypatch.chdir(tmp_path)
    output_dir = tmp_path / ".pbom"
    _emit_n_records(output_dir, 1)
    (output_dir / "corrupt.pbom.json").write_text("not-json", encoding="utf-8")
    runner = _runner()

    result = runner.invoke(main, ["records"])

    assert result.exit_code == 0
    assert "Unreadable files skipped: 1" in result.output
    assert "SEQ" in result.output


def test_records_last_zero_rejected_by_click(tmp_path, monkeypatch) -> None:
    """pbom records --last 0 should be rejected by click.IntRange."""
    monkeypatch.chdir(tmp_path)
    runner = _runner()
    runner.invoke(main, ["init"])

    result = runner.invoke(main, ["records", "--last", "0"])

    assert result.exit_code != 0
    assert "Invalid value" in result.output or result.exit_code == 2


def test_records_json_keeps_warning_on_stderr(tmp_path, monkeypatch) -> None:
    """Corrupt file + --format json: stdout is JSON; warning goes to stderr."""
    monkeypatch.chdir(tmp_path)
    output_dir = tmp_path / ".pbom"
    _emit_n_records(output_dir, 1)
    (output_dir / "corrupt.pbom.json").write_text("not-json", encoding="utf-8")
    # Click 8.4+ captures stdout/stderr separately by default (no mix_stderr).
    runner = CliRunner(catch_exceptions=False)

    result = runner.invoke(main, ["records", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    assert "@context" in payload[0]
    assert "Unreadable files skipped: 1" in result.stderr
    assert "Unreadable files skipped" not in result.stdout


def test_records_detail_starts_with_chain_sequence_number(
    tmp_path, monkeypatch
) -> None:
    """pbom records --record 1 detail should start with chain_sequence_number."""
    monkeypatch.chdir(tmp_path)
    _emit_n_records(tmp_path / ".pbom", 1)
    runner = _runner()

    result = runner.invoke(main, ["records", "--record", "1"])

    assert result.exit_code == 0
    first_line = result.output.splitlines()[0]
    assert first_line == "chain_sequence_number: 1"


def test_records_detail_none_hash_shows_na(tmp_path, monkeypatch) -> None:
    """Detail view should render a None response_hash as n/a."""
    monkeypatch.chdir(tmp_path)
    output_dir = tmp_path / ".pbom"
    _emit_n_records(output_dir, 1)
    files = sorted(output_dir.glob("*.pbom.json"))
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    payload["response"]["response_hash"] = None
    files[0].write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    runner = _runner()

    result = runner.invoke(main, ["records", "--record", "1"])

    assert result.exit_code == 0
    assert "response_hash: n/a" in result.output


def test_records_table_escapes_ansi_in_model_id(tmp_path, monkeypatch) -> None:
    """Table view must not emit raw ESC from a tampered model_id."""
    monkeypatch.chdir(tmp_path)
    output_dir = tmp_path / ".pbom"
    _emit_n_records(output_dir, 1)
    files = sorted(output_dir.glob("*.pbom.json"))
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    payload["inference"]["model_id"] = "\x1b[31mevil"
    files[0].write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    runner = _runner()

    result = runner.invoke(main, ["records"])

    assert result.exit_code == 0
    assert "\x1b" not in result.stdout
    assert "\\x1b" in result.stdout


def test_records_table_escapes_line_separator_in_model_id(
    tmp_path, monkeypatch
) -> None:
    """U+2028 in model_id must appear as \\u2028 in the table, not raw."""
    monkeypatch.chdir(tmp_path)
    output_dir = tmp_path / ".pbom"
    _emit_n_records(output_dir, 1)
    files = sorted(output_dir.glob("*.pbom.json"))
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    payload["inference"]["model_id"] = "pre\u2028post"
    files[0].write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    runner = _runner()

    result = runner.invoke(main, ["records"])

    assert result.exit_code == 0
    assert "\u2028" not in result.stdout
    assert "\\u2028" in result.stdout


def test_records_detail_escapes_bidi_in_evidence(tmp_path, monkeypatch) -> None:
    """Detail view must escape U+202E in action-primitive evidence."""
    monkeypatch.chdir(tmp_path)
    output_dir = tmp_path / ".pbom"
    _emit_n_records(output_dir, 1)
    files = sorted(output_dir.glob("*.pbom.json"))
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    payload["action_primitives"] = [
        {
            "primitive": "DATA_READ",
            "confidence": 0.9,
            "evidence": "safe\u202eevil",
            "location": None,
            "risk_level": "low",
            "category": "DATA_OPERATIONS",
        }
    ]
    files[0].write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    runner = _runner()

    result = runner.invoke(main, ["records", "--record", "1"])

    assert result.exit_code == 0
    assert "\u202e" not in result.stdout
    assert "\\u202e" in result.stdout


def test_validate_escapes_entry_id_on_broken_chain(tmp_path, monkeypatch) -> None:
    """Broken-chain detail must escape ESC/newline in entry_id; exit 1."""
    monkeypatch.chdir(tmp_path)
    output_dir = tmp_path / ".pbom"
    _emit_n_records(output_dir, 2)
    # Pin by sequence: broken-link details cite current.entry_id (seq 2).
    target_path = None
    for path in output_dir.glob("*.pbom.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload["identity"]["chain_sequence_number"] == 2:
            target_path = path
            second = payload
            break
    assert target_path is not None
    second["identity"]["previous_entry_hash"] = "0" * 64
    second["identity"]["entry_id"] = "id\x1b[10A\ninjected"
    target_path.write_text(
        json.dumps(second, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    runner = _runner()

    result = runner.invoke(main, ["validate"])

    assert result.exit_code == 1
    assert "\x1b" not in result.stdout
    # Escaped forms of the injected control chars from entry_id
    assert "\\x1b" in result.stdout
    assert "\\x0a" in result.stdout


def test_records_json_escapes_control_in_model_id(tmp_path, monkeypatch) -> None:
    """JSON output must not contain a raw ESC byte (json.dumps escapes it)."""
    monkeypatch.chdir(tmp_path)
    output_dir = tmp_path / ".pbom"
    _emit_n_records(output_dir, 1)
    files = sorted(output_dir.glob("*.pbom.json"))
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    payload["inference"]["model_id"] = "\x1b[31mevil"
    files[0].write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    runner = CliRunner(catch_exceptions=False)

    result = runner.invoke(main, ["records", "--format", "json"])

    assert result.exit_code == 0
    assert "\x1b" not in result.stdout
    json.loads(result.stdout)  # still valid JSON


def _write_deeply_nested_pbom(directory) -> None:
    """Write a crafted deeply nested JSON file that triggers RecursionError."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "nested.pbom.json").write_text(
        "[" * 200_000 + "]" * 200_000, encoding="utf-8"
    )


def test_records_deeply_nested_json_is_unreadable(tmp_path, monkeypatch) -> None:
    """Deep nesting must not crash records; count as unreadable on stderr."""
    monkeypatch.chdir(tmp_path)
    output_dir = tmp_path / ".pbom"
    _write_deeply_nested_pbom(output_dir)
    runner = CliRunner(catch_exceptions=False)

    result = runner.invoke(main, ["records"])

    assert result.exit_code == 0
    assert "Unreadable files skipped: 1" in result.stderr


def test_status_deeply_nested_json_is_unreadable(tmp_path, monkeypatch) -> None:
    """Deep nesting must not crash status; count as unreadable."""
    monkeypatch.chdir(tmp_path)
    output_dir = tmp_path / ".pbom"
    _write_deeply_nested_pbom(output_dir)
    runner = CliRunner(catch_exceptions=False)

    result = runner.invoke(main, ["status"])

    assert result.exit_code == 0
    assert "Unreadable files skipped: 1" in result.output


def test_validate_deeply_nested_json_fails(tmp_path, monkeypatch) -> None:
    """Deep nesting must not crash validate; unreadable → FAIL / exit 1."""
    monkeypatch.chdir(tmp_path)
    output_dir = tmp_path / ".pbom"
    _write_deeply_nested_pbom(output_dir)
    runner = CliRunner(catch_exceptions=False)

    result = runner.invoke(main, ["validate"])

    assert result.exit_code == 1
    assert "Validation: FAIL" in result.output


def test_records_warning_escapes_ansi_in_filename(
    tmp_path, monkeypatch, caplog
) -> None:
    """Parse-failure warnings must not emit raw ESC from the file name."""
    monkeypatch.chdir(tmp_path)
    output_dir = tmp_path / ".pbom"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "x\x1b[31mRED.pbom.json").write_text("not json", encoding="utf-8")
    runner = CliRunner(catch_exceptions=False)

    with caplog.at_level(logging.WARNING, logger="pbom"):
        result = runner.invoke(main, ["records"])

    assert result.exit_code == 0
    assert "\x1b" not in caplog.text


def test_validate_reports_noncanonical_records(tmp_path, monkeypatch) -> None:
    """pbom validate should report Non-canonical records and exit 1."""
    monkeypatch.chdir(tmp_path)
    output_dir = tmp_path / ".pbom"
    _emit_n_records(output_dir, 3)
    target = None
    for path in output_dir.glob("*.pbom.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload["identity"]["chain_sequence_number"] == 2:
            target = path
            break
    assert target is not None
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["prompt"]["raw_content"]["injected_note"] = "tamper"
    target.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    runner = CliRunner(catch_exceptions=False)

    result = runner.invoke(main, ["validate"])

    assert result.exit_code == 1
    assert "Non-canonical records: 1" in result.output


def _run_pbom_subprocess(
    args: list[str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    """Invoke the pbom CLI in a subprocess with a hang-detecting timeout."""
    argv = ["pbom", *args]
    script = (
        "import sys\n"
        "from pbom.cli import main\n"
        f"sys.argv = {argv!r}\n"
        "main()\n"
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=_SPECIAL_FILE_TIMEOUT_S,
        check=False,
    )


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="os.mkfifo unavailable")
def test_fifo_does_not_hang_validate_or_records(tmp_path) -> None:
    """A FIFO matching *.pbom.json must not hang validate/records."""
    pbom_dir = tmp_path / ".pbom"
    pbom_dir.mkdir()
    os.mkfifo(pbom_dir / "zz.pbom.json")

    validate = _run_pbom_subprocess(["validate"], tmp_path)
    assert validate.returncode == 1
    assert "Validation: FAIL" in validate.stdout

    records = _run_pbom_subprocess(["records"], tmp_path)
    assert records.returncode == 0
    assert "Unreadable files skipped: 1" in records.stderr


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="os.mkfifo unavailable")
def test_fifo_does_not_hang_emitter_construction(tmp_path) -> None:
    """Emitter construction must not hang; resume raises ChainCorruptedError."""
    pbom_dir = tmp_path / ".pbom"
    pbom_dir.mkdir()
    os.mkfifo(pbom_dir / "zz.pbom.json")
    script = (
        "from pbom import PBOMEmitter, ChainCorruptedError\n"
        f"try:\n"
        f"    PBOMEmitter(application_id='t', output_dir=r'{pbom_dir}')\n"
        f"except ChainCorruptedError:\n"
        f"    raise SystemExit(0)\n"
        f"raise SystemExit(2)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=_SPECIAL_FILE_TIMEOUT_S,
        check=False,
    )
    assert result.returncode == 0


def test_symlink_record_is_unreadable(tmp_path) -> None:
    """A symlink *.pbom.json must be treated as unreadable by validate."""
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    _emit_n_records(real_dir, 1)
    real_file = next(real_dir.glob("*.pbom.json"))
    pbom_dir = tmp_path / ".pbom"
    pbom_dir.mkdir()
    link_path = pbom_dir / "linked.pbom.json"
    try:
        link_path.symlink_to(real_file)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unsupported on this platform")

    result = _run_pbom_subprocess(["validate", str(pbom_dir)], tmp_path)

    assert result.returncode == 1
    assert "FAIL" in result.stdout or "Unreadable" in result.stdout


def test_honest_chain_still_passes_after_safe_io(tmp_path, monkeypatch) -> None:
    """Regular files still validate and list after safe-io wiring."""
    monkeypatch.chdir(tmp_path)
    _emit_n_records(tmp_path / ".pbom", 2)
    runner = _runner()

    validate = runner.invoke(main, ["validate"])
    records = runner.invoke(main, ["records"])

    assert validate.exit_code == 0
    assert "PASS" in validate.output
    assert records.exit_code == 0
    assert "SEQ" in records.output


def _symlink_or_skip(link: Path, target: Path) -> None:
    """Create a symlink, or skip the test if the platform disallows it."""
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unsupported on this platform")


def test_init_and_install_skill_refuse_symlinked_targets(
    tmp_path, monkeypatch
) -> None:
    """Outside targets stay ORIGINAL; install-skill exits 1."""
    outside = tmp_path / "outside"
    outside.mkdir()
    for name in ("CLAUDE.md", ".gitignore", "SKILL.md"):
        (outside / name).write_text("ORIGINAL\n", encoding="utf-8")

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    (repo / ".claude" / "skills" / "pbom").mkdir(parents=True)
    _symlink_or_skip(repo / "CLAUDE.md", outside / "CLAUDE.md")
    _symlink_or_skip(repo / ".gitignore", outside / ".gitignore")
    _symlink_or_skip(
        repo / ".claude" / "skills" / "pbom" / "SKILL.md", outside / "SKILL.md"
    )

    runner = _runner()
    init = runner.invoke(main, ["init"])
    install = runner.invoke(main, ["install-skill", "--force"])

    assert init.exit_code == 0
    assert install.exit_code == 1
    for name in ("CLAUDE.md", ".gitignore", "SKILL.md"):
        assert (outside / name).read_text(encoding="utf-8") == "ORIGINAL\n"


def test_install_skill_refuses_symlinked_claude_dir(tmp_path, monkeypatch) -> None:
    """Symlinked .claude → install-skill exit 1, outside dir untouched."""
    outside = tmp_path / "outside_claude"
    outside.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    _symlink_or_skip(repo / ".claude", outside)

    runner = _runner()
    result = runner.invoke(main, ["install-skill"])

    assert result.exit_code == 1
    assert "refusing to write through symlink" in result.output
    assert list(outside.iterdir()) == []


def test_init_skips_symlinked_pbom_config(tmp_path, monkeypatch) -> None:
    """Symlinked .pbom → exit 0, outside config.json unchanged, warning."""
    outside = tmp_path / "outside_pbom"
    outside.mkdir()
    (outside / "config.json").write_text("ORIGINAL\n", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    _symlink_or_skip(repo / ".pbom", outside)

    runner = _runner()
    result = runner.invoke(main, ["init"])

    assert result.exit_code == 0
    assert "not writing config through symlinked .pbom/" in result.output
    assert (outside / "config.json").read_text(encoding="utf-8") == "ORIGINAL\n"


def test_init_skips_dangling_pbom_symlink(tmp_path, monkeypatch) -> None:
    """Dangling .pbom symlink → exit 0, warning, target still missing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    missing_target = tmp_path / "does_not_exist"
    _symlink_or_skip(repo / ".pbom", missing_target)

    runner = _runner()
    result = runner.invoke(main, ["init"])

    assert result.exit_code == 0
    assert "not writing config through symlinked .pbom/" in result.output
    assert not missing_target.exists()


def test_init_and_install_skill_without_symlinks(tmp_path, monkeypatch) -> None:
    """No symlinks → init + install-skill succeed as before."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text("venv/\n", encoding="utf-8")
    runner = _runner()

    init = runner.invoke(main, ["init"])
    install = runner.invoke(main, ["install-skill"])

    assert init.exit_code == 0
    assert (tmp_path / ".pbom" / "config.json").exists()
    assert ".pbom/" in (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert install.exit_code == 0
    assert (tmp_path / ".claude" / "skills" / "pbom" / "SKILL.md").exists()
    assert (tmp_path / "CLAUDE.md").exists()
