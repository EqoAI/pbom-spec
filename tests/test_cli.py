"""Tests for PBOM CLI commands."""

from __future__ import annotations

import json

from click.testing import CliRunner

from pbom.cli import main
from pbom.emitter import PBOMEmitter


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
