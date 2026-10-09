"""Tests for PBOM schema models and schema export."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pbom.schema import (
    ActionPrimitiveDetection,
    PBOM_VERSION,
    ActionPrimitive,
    CryptographicCommitment,
    EntryIdentity,
    InferenceMetadata,
    PBOMRecord,
    Principal,
    PromptRecord,
    RawContent,
    ResponseRecord,
    Telemetry,
    export_json_schema,
)


def _minimal_record(**overrides) -> PBOMRecord:
    """Create a valid minimal PBOMRecord for schema-focused tests."""
    entry_id = str(uuid4())
    base = {
        "id_": f"urn:uuid:{entry_id}",
        "identity": EntryIdentity(
            pbom_version=PBOM_VERSION,
            entry_id=entry_id,
            chain_sequence_number=1,
            previous_entry_hash=None,
            created_at_iso="2026-05-29T22:00:00.000Z",
            created_at_epoch_ms=1770000000000,
            entry_signature=None,
        ),
        "principal": Principal(
            application_id="test-app",
            sdk_name="pbom-python",
            sdk_version="0.1.0",
        ),
        "commitment": CryptographicCommitment(
            commitment_type="pre_inference",
            nonce="a" * 32,
            commitment_hash="b" * 64,
            commitment_ts=1770000000000,
            nonce_revealed_ts=1770000000001,
            commitment_verified=True,
        ),
        "prompt": PromptRecord(
            raw_content=RawContent(
                system_prompt_hash="1" * 64,
                user_prompt_hash="2" * 64,
                full_prompt_hash="3" * 64,
                system_prompt_token_count=5,
                total_input_token_count=11,
                system_prompt_text=None,
                user_prompt_text=None,
            ),
            template=None,
            structural_fingerprint=None,
        ),
        "inference": InferenceMetadata(
            model_id="openai/gpt-4o",
            model_family="gpt-4o",
            model_provider="openai",
            temperature=0.0,
            max_tokens=256,
            streaming=False,
            context_window_max=128000,
            context_utilization_pct=0.01,
        ),
        "response": ResponseRecord(
            response_hash="4" * 64,
            response_token_count=10,
            stop_reason="end_turn",
            thinking_token_count=0,
            response_text=None,
        ),
        "telemetry": Telemetry(
            total_latency_ms=100,
            inference_latency_ms=80,
        ),
        "context_management": None,
        "provider_metadata": None,
        "structural_analysis": None,
        "action_primitives": [],
        "extensions": {},
        "storage_mode": "fingerprint",
    }
    base.update(overrides)
    return PBOMRecord(**base)


def test_pbom_version_constant_is_1_0_0() -> None:
    """PBOM_VERSION constant should be fixed to 1.0.0."""
    assert PBOM_VERSION == "1.0.0"


def test_jsonld_alias_round_trip_uses_at_prefixed_keys() -> None:
    """Dumping by alias should emit @context/@type/@id keys."""
    record = _minimal_record()

    dumped = record.model_dump(by_alias=True)

    assert "@context" in dumped
    assert "@type" in dumped
    assert "@id" in dumped
    assert dumped["@context"] == "https://pbom.org/context/v1"
    assert dumped["@type"] == "PBOMRecord"
    assert dumped["@id"].startswith("urn:uuid:")


def test_jsonld_fields_accept_python_field_names_with_populate_by_name() -> None:
    """Model should accept Python field names for JSON-LD envelope fields."""
    record = _minimal_record(
        context_="https://pbom.org/context/v1",
        type_="PBOMRecord",
        id_=f"urn:uuid:{uuid4()}",
    )

    dumped = record.model_dump(by_alias=True)

    assert dumped["@context"] == "https://pbom.org/context/v1"
    assert dumped["@type"] == "PBOMRecord"
    assert dumped["@id"].startswith("urn:uuid:")


def test_null_fields_are_preserved_in_model_dump_by_alias() -> None:
    """model_dump(by_alias=True) should preserve explicit null values."""
    record = _minimal_record(
        identity=EntryIdentity(
            pbom_version=PBOM_VERSION,
            entry_id=str(uuid4()),
            chain_sequence_number=1,
            previous_entry_hash=None,
            created_at_iso="2026-05-29T22:00:00.000Z",
            created_at_epoch_ms=1770000000000,
            entry_signature=None,
        )
    )

    dumped = record.model_dump(by_alias=True)

    assert "previous_entry_hash" in dumped["identity"]
    assert dumped["identity"]["previous_entry_hash"] is None


def test_extensions_round_trip_preserves_keys_and_values() -> None:
    """Extensions should preserve exact namespaced keys and values."""
    record = _minimal_record(
        extensions={"mytool.verdict": "safe", "other.score": 42},
    )

    dumped = record.model_dump()

    assert dumped["extensions"] == {"mytool.verdict": "safe", "other.score": 42}


def test_extensions_default_to_empty_dict() -> None:
    """extensions should default to an empty dictionary."""
    record = _minimal_record()

    assert record.extensions == {}


def test_extra_fields_are_forbidden() -> None:
    """Unexpected top-level fields should raise ValidationError."""
    with pytest.raises(ValidationError):
        _minimal_record(bogus_field="test")


def test_action_primitive_enum_has_19_values() -> None:
    """Guard against silent ActionPrimitive enum drift from the canonical 19-value count."""
    assert len(ActionPrimitive) == 19


def test_export_json_schema_writes_valid_json(tmp_path) -> None:
    """export_json_schema should write a valid JSON file to disk."""
    output_path = tmp_path / "schema.json"

    export_json_schema(output_path)

    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)


def test_to_json_dict_matches_alias_dump() -> None:
    """to_json_dict should be equivalent to model_dump(by_alias=True)."""
    record = _minimal_record()

    assert record.to_json_dict() == record.model_dump(by_alias=True)


def test_example_record_json_round_trips_through_model() -> None:
    """Example fixture should validate and preserve core identifiers."""
    payload = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "examples"
            / "example-record.json"
        ).read_text(encoding="utf-8")
    )
    record = PBOMRecord.model_validate(payload)
    dumped = record.to_json_dict()

    assert dumped["@id"] == payload["@id"]
    assert dumped["identity"]["entry_id"] == payload["identity"]["entry_id"]
    assert dumped["identity"]["pbom_version"] == "1.0.0"


def test_action_primitive_detection_rejects_out_of_range_confidence() -> None:
    """Confidence must remain within [0.0, 1.0]."""
    with pytest.raises(ValidationError):
        ActionPrimitiveDetection(
            primitive=ActionPrimitive.DATA_READ,
            confidence=1.1,
            evidence="evidence",
            location=None,
            risk_level="low",
            category="DATA_OPERATIONS",
        )


def test_importing_schema_emits_no_user_warnings() -> None:
    """pbom.schema must import cleanly under -W error::UserWarning."""
    result = subprocess.run(
        [sys.executable, "-W", "error::UserWarning", "-c", "import pbom.schema"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
