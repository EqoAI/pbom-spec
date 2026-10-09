"""Tests for PBOM chain and commitment validation."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from uuid import uuid4

from pbom.emitter import PBOMEmitter
from pbom.schema import PBOMRecord
from pbom.validator import ValidationResult, validate_chain, validate_commitment


def _minimal_record_dict(
    *,
    sequence: int,
    previous_entry_hash: str | None,
    entry_id: str | None = None,
) -> dict:
    """Build a minimal valid PBOMRecord dict for synthetic chain tests."""
    record_id = entry_id or str(uuid4())
    return {
        "@context": "https://pbom.org/context/v1",
        "@type": "PBOMRecord",
        "@id": f"urn:uuid:{record_id}",
        "identity": {
            "pbom_version": "1.0.0",
            "entry_id": record_id,
            "chain_sequence_number": sequence,
            "previous_entry_hash": previous_entry_hash,
            "created_at_iso": "2026-05-29T22:00:00.000Z",
            "created_at_epoch_ms": 1770000000000 + sequence,
            "entry_signature": None,
        },
        "principal": {
            "application_id": "validator-test",
            "sdk_name": "pbom-python",
            "sdk_version": "0.1.0",
        },
        "commitment": {
            "commitment_type": "pre_inference",
            "nonce": "a" * 32,
            "commitment_hash": "b" * 64,
            "commitment_ts": 1770000000000,
            "nonce_revealed_ts": 1770000000001,
            "commitment_verified": True,
        },
        "prompt": {
            "raw_content": {
                "system_prompt_hash": "1" * 64,
                "user_prompt_hash": "2" * 64,
                "full_prompt_hash": "3" * 64,
                "system_prompt_token_count": 5,
                "total_input_token_count": 10,
                "system_prompt_text": None,
                "user_prompt_text": None,
            },
            "template": None,
            "structural_fingerprint": None,
        },
        "inference": {
            "model_id": "openai/gpt-4o",
            "model_family": "gpt-4o",
            "model_provider": "openai",
            "temperature": 0.0,
            "max_tokens": 256,
            "streaming": False,
            "context_window_max": 128000,
            "context_utilization_pct": 0.01,
        },
        "response": {
            "response_hash": "4" * 64,
            "response_token_count": 7,
            "stop_reason": "end_turn",
            "thinking_token_count": 0,
            "response_text": None,
        },
        "telemetry": {
            "total_latency_ms": 100,
            "inference_latency_ms": 80,
        },
        "context_management": None,
        "provider_metadata": None,
        "structural_analysis": None,
        "action_primitives": [],
        "extensions": {},
        "storage_mode": "fingerprint",
    }


def _write_record(path: Path, payload: dict) -> None:
    """Write a PBOM JSON payload using pretty formatting."""
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def test_empty_directory_is_valid(tmp_path) -> None:
    """Empty directory should be considered a valid chain."""
    result = validate_chain(tmp_path)

    assert isinstance(result, ValidationResult)
    assert result.total_records == 0
    assert result.is_valid is True


def test_single_record_is_valid_with_zero_links(tmp_path) -> None:
    """A single emitted record should validate with zero link checks."""
    emitter = PBOMEmitter(
        application_id="test", output_dir=tmp_path, sdk_version="0.1.0"
    )
    with emitter.commit("sys", "user") as ctx:
        ctx.complete(model_id="openai/gpt-4o", response_text="resp")

    result = validate_chain(tmp_path)
    assert result.is_valid is True
    assert result.total_records == 1
    assert result.valid_links == 0


def test_two_record_chain_is_valid_with_one_link(tmp_path) -> None:
    """Two sequential records should produce one valid chain link."""
    emitter = PBOMEmitter(
        application_id="test", output_dir=tmp_path, sdk_version="0.1.0"
    )
    with emitter.commit("sys1", "user1") as ctx:
        ctx.complete(model_id="openai/gpt-4o", response_text="resp1")
    with emitter.commit("sys2", "user2") as ctx:
        ctx.complete(model_id="openai/gpt-4o", response_text="resp2")

    result = validate_chain(tmp_path)
    assert result.is_valid is True
    assert result.valid_links == 1


def test_broken_hash_link_is_detected(tmp_path) -> None:
    """Tampering previous_entry_hash should produce a broken link finding."""
    emitter = PBOMEmitter(
        application_id="test", output_dir=tmp_path, sdk_version="0.1.0"
    )
    with emitter.commit("sys1", "user1") as ctx:
        ctx.complete(model_id="openai/gpt-4o", response_text="resp1")
    with emitter.commit("sys2", "user2") as ctx:
        ctx.complete(model_id="openai/gpt-4o", response_text="resp2")

    files = sorted(tmp_path.glob("*.pbom.json"))
    second_payload = json.loads(files[1].read_text(encoding="utf-8"))
    second_payload["identity"]["previous_entry_hash"] = "0" * 64
    _write_record(files[1], second_payload)

    result = validate_chain(tmp_path)
    assert result.is_valid is False
    assert len(result.broken_links) == 1


def test_sequence_gap_is_detected(tmp_path) -> None:
    """Missing sequence numbers should be reported as sequence gaps."""
    record1 = _minimal_record_dict(sequence=1, previous_entry_hash=None)
    record3 = _minimal_record_dict(sequence=3, previous_entry_hash="f" * 64)
    _write_record(tmp_path / f"{uuid4()}.pbom.json", record1)
    _write_record(tmp_path / f"{uuid4()}.pbom.json", record3)

    result = validate_chain(tmp_path)
    assert result.is_valid is False
    assert (2, 2) in result.sequence_gaps


def test_duplicate_sequence_is_detected(tmp_path) -> None:
    """Duplicate sequence numbers should be reported."""
    record_a = _minimal_record_dict(sequence=1, previous_entry_hash=None, entry_id="a")
    record_b = _minimal_record_dict(sequence=1, previous_entry_hash=None, entry_id="b")
    _write_record(tmp_path / "a.pbom.json", record_a)
    _write_record(tmp_path / "b.pbom.json", record_b)

    result = validate_chain(tmp_path)
    assert result.is_valid is False
    assert 1 in result.duplicate_sequences


def test_unreadable_file_is_reported_and_invalidates_chain(tmp_path) -> None:
    """Unreadable JSON files should be tracked and mark chain invalid."""
    (tmp_path / "bad.pbom.json").write_text("not valid json", encoding="utf-8")

    result = validate_chain(tmp_path)
    assert result.is_valid is False
    assert len(result.unreadable_files) == 1


def test_validate_commitment_returns_true_in_forensic_mode(tmp_path) -> None:
    """Forensic records should be commitment-verifiable."""
    emitter = PBOMEmitter(
        application_id="test",
        output_dir=tmp_path,
        storage_mode="forensic",
        sdk_version="0.1.0",
    )
    with emitter.commit("sys", "user") as ctx:
        record = ctx.complete(model_id="openai/gpt-4o", response_text="resp")

    assert validate_commitment(record) is True


def test_validate_commitment_returns_none_in_fingerprint_mode(tmp_path) -> None:
    """Fingerprint records should be unverifiable and return None."""
    emitter = PBOMEmitter(
        application_id="test",
        output_dir=tmp_path,
        storage_mode="fingerprint",
        sdk_version="0.1.0",
    )
    with emitter.commit("sys", "user") as ctx:
        record = ctx.complete(model_id="openai/gpt-4o", response_text="resp")

    assert validate_commitment(record) is None


def test_validate_commitment_detects_tampered_nonce(tmp_path) -> None:
    """Mutating nonce on a forensic record should fail commitment verification."""
    emitter = PBOMEmitter(
        application_id="test",
        output_dir=tmp_path,
        storage_mode="forensic",
        sdk_version="0.1.0",
    )
    with emitter.commit("sys", "user") as ctx:
        record = ctx.complete(model_id="openai/gpt-4o", response_text="resp")

    payload = record.model_dump(by_alias=True)
    tampered = PBOMRecord.model_validate(payload)
    tampered.commitment.nonce = "0" * 32

    assert validate_commitment(tampered) is False


def test_failure_details_include_human_readable_broken_link_message(tmp_path) -> None:
    """Broken-link failures should include human-readable detail text."""
    emitter = PBOMEmitter(
        application_id="test", output_dir=tmp_path, sdk_version="0.1.0"
    )
    with emitter.commit("sys1", "user1") as ctx:
        ctx.complete(model_id="openai/gpt-4o", response_text="resp1")
    with emitter.commit("sys2", "user2") as ctx:
        ctx.complete(model_id="openai/gpt-4o", response_text="resp2")

    files = sorted(tmp_path.glob("*.pbom.json"))
    payload = json.loads(files[1].read_text(encoding="utf-8"))
    payload["identity"]["previous_entry_hash"] = "0" * 64
    _write_record(files[1], payload)

    result = validate_chain(tmp_path)
    assert result.details
    assert any("broken chain link" in detail.lower() for detail in result.details)


def test_validate_chain_mixed_modes_aggregates_commitment_results(tmp_path) -> None:
    """Validation should aggregate verified and unverifiable commitments correctly."""
    forensic = PBOMEmitter(
        application_id="test",
        output_dir=tmp_path,
        storage_mode="forensic",
        sdk_version="0.1.0",
    )
    with forensic.commit("sys-1", "user-1") as ctx:
        ctx.complete(model_id="openai/gpt-4o", response_text="resp-1")

    fingerprint = PBOMEmitter(
        application_id="test",
        output_dir=tmp_path,
        storage_mode="fingerprint",
        sdk_version="0.1.0",
    )
    with fingerprint.commit("sys-2", "user-2") as ctx:
        ctx.complete(model_id="openai/gpt-4o", response_text="resp-2")

    result = validate_chain(tmp_path)
    assert result.is_valid is True
    assert result.commitment_results["verified"] == 1
    assert result.commitment_results["unverifiable"] == 1
    assert result.commitment_results["failed"] == 0


def test_validate_commitment_returns_false_when_commitment_hash_is_none(
    tmp_path,
) -> None:
    """A missing commitment hash should be treated as failed verification."""
    emitter = PBOMEmitter(
        application_id="test",
        output_dir=tmp_path,
        storage_mode="forensic",
        sdk_version="0.1.0",
    )
    with emitter.commit("sys", "user") as ctx:
        record = ctx.complete(model_id="openai/gpt-4o", response_text="resp")

    payload = record.model_dump(by_alias=True)
    payload["commitment"]["commitment_hash"] = None
    mutated = PBOMRecord.model_validate(payload)

    assert validate_commitment(mutated) is False


def test_validate_commitment_returns_false_on_tampered_prompt_text(tmp_path) -> None:
    """Changing stored forensic prompt text should break commitment verification."""
    emitter = PBOMEmitter(
        application_id="test",
        output_dir=tmp_path,
        storage_mode="forensic",
        sdk_version="0.1.0",
    )
    with emitter.commit("sys", "user") as ctx:
        record = ctx.complete(model_id="openai/gpt-4o", response_text="resp")

    payload = record.model_dump(by_alias=True)
    payload["prompt"]["raw_content"]["system_prompt_text"] = "tampered"
    mutated = PBOMRecord.model_validate(payload)

    assert validate_commitment(mutated) is False


def test_schema_invalid_file_is_reported_as_unreadable(tmp_path) -> None:
    """Schema-invalid record payload should be counted as unreadable."""
    invalid_payload = {
        "@context": "https://pbom.org/context/v1",
        "@type": "PBOMRecord",
        "@id": "urn:uuid:bad",
        "identity": {"entry_id": "bad", "chain_sequence_number": 1},
    }
    _write_record(tmp_path / "bad.pbom.json", invalid_payload)

    result = validate_chain(tmp_path)
    assert result.is_valid is False
    assert len(result.unreadable_files) == 1


def test_validate_chain_deeply_nested_json_is_unreadable(tmp_path) -> None:
    """validate_chain must catch RecursionError and mark file unreadable."""
    nested = tmp_path / "nested.pbom.json"
    nested.write_text("[" * 200_000 + "]" * 200_000, encoding="utf-8")

    result = validate_chain(tmp_path)

    assert result.is_valid is False
    assert len(result.unreadable_files) == 1
    assert str(nested) in result.unreadable_files


def test_validate_chain_warning_omits_forensic_input_values(tmp_path, caplog) -> None:
    """ValidationError warnings must not leak forensic prompt text."""
    emitter = PBOMEmitter(
        application_id="test",
        output_dir=tmp_path,
        storage_mode="forensic",
        sdk_version="0.1.0",
    )
    with emitter.commit("SYS-SECRET-MARKER", "user") as ctx:
        ctx.complete(model_id="openai/gpt-4o", response_text="resp")
    path = next(tmp_path.glob("*.pbom.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["prompt"]["raw_content"]["system_prompt_token_count"]
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )

    with caplog.at_level(logging.WARNING, logger="pbom"):
        result = validate_chain(tmp_path)

    assert result.is_valid is False
    assert "SECRET-MARKER" not in caplog.text
    assert "system_prompt_token_count" in caplog.text


def test_validate_chain_warning_escapes_evil_extra_key(tmp_path, caplog) -> None:
    """Extra-key locations with ESC must not appear raw in warnings."""
    payload = _minimal_record_dict(sequence=1, previous_entry_hash=None)
    payload["\x1b[31mevil"] = "x"
    _write_record(tmp_path / "evil.pbom.json", payload)

    with caplog.at_level(logging.WARNING, logger="pbom"):
        validate_chain(tmp_path)

    assert "\x1b" not in caplog.text


def _path_for_sequence(directory: Path, sequence: int) -> Path:
    """Return the on-disk path for the record with the given sequence number."""
    for path in directory.glob("*.pbom.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload["identity"]["chain_sequence_number"] == sequence:
            return path
    raise AssertionError(f"no record with sequence {sequence}")


def _emit_three(directory: Path, **emitter_kwargs: object) -> None:
    """Emit a three-record chain into ``directory``."""
    emitter = PBOMEmitter(
        application_id="test",
        output_dir=directory,
        sdk_version="0.1.0",
        **emitter_kwargs,  # type: ignore[arg-type]
    )
    for i in range(3):
        with emitter.commit(f"sys{i}", f"user{i}") as ctx:
            ctx.complete(model_id="openai/gpt-4o", response_text=f"resp{i}")


def test_nested_unknown_field_marks_noncanonical(tmp_path) -> None:
    """Unknown nested field in a middle record must fail as non-canonical."""
    _emit_three(tmp_path)
    path = _path_for_sequence(tmp_path, 2)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["prompt"]["raw_content"]["injected_note"] = "tamper"
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    result = validate_chain(tmp_path)

    assert result.is_valid is False
    assert str(path) in result.noncanonical_files


def test_duplicate_key_marks_noncanonical(tmp_path) -> None:
    """Duplicate JSON keys in a middle record must fail as non-canonical."""
    _emit_three(tmp_path)
    path = _path_for_sequence(tmp_path, 2)
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        '"model_id":',
        '"model_id": "FAKE-MODEL", "model_id":',
        1,
    )
    path.write_text(text, encoding="utf-8")

    result = validate_chain(tmp_path)

    assert result.is_valid is False
    assert str(path) in result.noncanonical_files


def test_string_sequence_number_marks_noncanonical(tmp_path) -> None:
    """Type-coerced chain_sequence_number must fail as non-canonical."""
    _emit_three(tmp_path)
    path = _path_for_sequence(tmp_path, 2)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["identity"]["chain_sequence_number"] = "2"
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    result = validate_chain(tmp_path)

    assert result.is_valid is False
    assert str(path) in result.noncanonical_files


def test_honest_chains_are_canonical(tmp_path) -> None:
    """Emitter-built chains must remain canonical across APIs and modes."""
    cases = [
        tmp_path / "fingerprint",
        tmp_path / "forensic",
        tmp_path / "record",
        tmp_path / "blocked",
        tmp_path / "extensions",
    ]
    for case_dir in cases:
        case_dir.mkdir()

    _emit_three(cases[0], storage_mode="fingerprint")
    _emit_three(cases[1], storage_mode="forensic")

    post_hoc = PBOMEmitter(
        application_id="test", output_dir=cases[2], sdk_version="0.1.0"
    )
    post_hoc.record(
        system_prompt="sys",
        user_prompt="user",
        model_id="openai/gpt-4o",
        response_text="resp",
    )

    blocked = PBOMEmitter(
        application_id="test", output_dir=cases[3], sdk_version="0.1.0"
    )
    blocked.record_blocked(
        system_prompt="sys",
        user_prompt="user",
        model_id="openai/gpt-4o",
    )

    with_ext = PBOMEmitter(
        application_id="test", output_dir=cases[4], sdk_version="0.1.0"
    )
    with with_ext.commit("sys", "user") as ctx:
        ctx.complete(
            model_id="openai/gpt-4o",
            response_text="resp",
            extensions={"tool.key": {"nested": [1, 2.5, None, True]}},
        )

    for case_dir in cases:
        result = validate_chain(case_dir)
        assert result.is_valid is True, case_dir.name
        assert result.noncanonical_files == [], case_dir.name


def test_validate_chain_allows_single_non_one_sequence_for_current_behavior(
    tmp_path,
) -> None:
    """Document current validator behavior for lone non-anchored sequence."""
    # Note: ChainState.resume_from rejects this shape. This test locks the
    # validator's current behavior so asymmetry is explicit and intentional.
    payload = _minimal_record_dict(sequence=2, previous_entry_hash="f" * 64)
    _write_record(tmp_path / "only.pbom.json", payload)

    result = validate_chain(tmp_path)
    assert result.is_valid is True
