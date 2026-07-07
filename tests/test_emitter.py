"""Tests for PBOMEmitter APIs and record emission behavior."""

from __future__ import annotations

import json
import time

import pytest

from pbom.emitter import PBOMEmitter
from pbom.exceptions import InvalidCommitmentError
from pbom.hashing import compute_sha256
from pbom.schema import PBOMRecord


def test_api1_basic_flow_returns_pre_inference_verified_record(tmp_path) -> None:
    """commit() + complete() should emit pre_inference record with verified commitment."""
    emitter = PBOMEmitter(
        application_id="test", output_dir=tmp_path, sdk_version="0.1.0"
    )

    with emitter.commit("You are helpful.", "Hello!") as ctx:
        record = ctx.complete(
            model_id="openai/gpt-4o",
            response_text="Hi there.",
        )

    assert isinstance(record, PBOMRecord)
    assert record.commitment.commitment_type == "pre_inference"
    assert record.commitment.commitment_verified is True


def test_api2_basic_flow_returns_post_hoc_unverified_record(tmp_path) -> None:
    """record() should emit post_hoc record with unverified commitment flag."""
    emitter = PBOMEmitter(
        application_id="test", output_dir=tmp_path, sdk_version="0.1.0"
    )

    record = emitter.record(
        system_prompt="You are helpful.",
        user_prompt="Hello!",
        model_id="openai/gpt-4o",
        response_text="Hi there.",
    )

    assert isinstance(record, PBOMRecord)
    assert record.commitment.commitment_type == "post_hoc"
    assert record.commitment.commitment_verified is False


def test_api1_writes_single_valid_json_file(tmp_path) -> None:
    """API 1 completion should write exactly one valid .pbom.json file."""
    emitter = PBOMEmitter(
        application_id="test", output_dir=tmp_path, sdk_version="0.1.0"
    )

    with emitter.commit("sys", "user") as ctx:
        ctx.complete(model_id="openai/gpt-4o", response_text="resp")

    files = sorted(tmp_path.glob("*.pbom.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert isinstance(payload, dict)


def test_api2_writes_record_file(tmp_path) -> None:
    """API 2 record() should write a .pbom.json file."""
    emitter = PBOMEmitter(
        application_id="test", output_dir=tmp_path, sdk_version="0.1.0"
    )

    emitter.record(
        system_prompt="sys",
        user_prompt="user",
        model_id="openai/gpt-4o",
        response_text="resp",
    )

    assert len(list(tmp_path.glob("*.pbom.json"))) == 1


def test_fingerprint_mode_omits_raw_text_fields(tmp_path) -> None:
    """Default fingerprint mode should keep hashes and omit raw text payloads."""
    emitter = PBOMEmitter(
        application_id="test", output_dir=tmp_path, sdk_version="0.1.0"
    )

    with emitter.commit("sys prompt", "user prompt") as ctx:
        record = ctx.complete(model_id="openai/gpt-4o", response_text="resp text")

    raw = record.prompt.raw_content
    assert raw.system_prompt_hash is not None
    assert raw.user_prompt_hash is not None
    assert raw.full_prompt_hash is not None
    assert raw.system_prompt_text is None
    assert raw.user_prompt_text is None
    assert record.response.response_text is None
    assert record.storage_mode == "fingerprint"


def test_forensic_mode_includes_raw_text_fields(tmp_path) -> None:
    """Forensic mode should include original prompt/response text."""
    emitter = PBOMEmitter(
        application_id="test",
        output_dir=tmp_path,
        storage_mode="forensic",
        sdk_version="0.1.0",
    )

    system_prompt = "sys prompt"
    user_prompt = "user prompt"
    response_text = "resp text"
    with emitter.commit(system_prompt, user_prompt) as ctx:
        record = ctx.complete(model_id="openai/gpt-4o", response_text=response_text)

    raw = record.prompt.raw_content
    assert raw.system_prompt_text == system_prompt
    assert raw.user_prompt_text == user_prompt
    assert record.response.response_text == response_text
    assert record.storage_mode == "forensic"


def test_first_record_previous_hash_is_none_and_key_present(tmp_path) -> None:
    """First record should anchor chain with previous_entry_hash set to null."""
    emitter = PBOMEmitter(
        application_id="test", output_dir=tmp_path, sdk_version="0.1.0"
    )

    with emitter.commit("sys", "user") as ctx:
        record = ctx.complete(model_id="openai/gpt-4o", response_text="resp")

    assert record.identity.previous_entry_hash is None
    dumped = record.model_dump(by_alias=True)
    assert "previous_entry_hash" in dumped["identity"]
    assert dumped["identity"]["previous_entry_hash"] is None


def test_chain_linkage_across_two_records(tmp_path) -> None:
    """Second emitted record should reference first record hash and sequence 2."""
    emitter = PBOMEmitter(
        application_id="test", output_dir=tmp_path, sdk_version="0.1.0"
    )

    with emitter.commit("sys1", "user1") as ctx:
        ctx.complete(model_id="openai/gpt-4o", response_text="resp1")
    with emitter.commit("sys2", "user2") as ctx:
        second = ctx.complete(model_id="openai/gpt-4o", response_text="resp2")

    assert second.identity.chain_sequence_number == 2
    assert second.identity.previous_entry_hash is not None


def test_model_fields_pass_through_exactly(tmp_path) -> None:
    """Model metadata should be stored exactly as provided by caller."""
    emitter = PBOMEmitter(
        application_id="test", output_dir=tmp_path, sdk_version="0.1.0"
    )

    with emitter.commit("sys", "user") as ctx:
        record = ctx.complete(
            model_id="openai/gpt-4o-mini",
            model_family="gpt-4o",
            model_provider="openai",
            response_text="resp",
        )

    assert record.inference.model_id == "openai/gpt-4o-mini"
    assert record.inference.model_family == "gpt-4o"
    assert record.inference.model_provider == "openai"


def test_incomplete_commit_writes_no_file(tmp_path) -> None:
    """Exiting commit context without complete() should not emit any file."""
    emitter = PBOMEmitter(
        application_id="test", output_dir=tmp_path, sdk_version="0.1.0"
    )

    with emitter.commit("sys", "user"):
        pass

    assert list(tmp_path.glob("*.pbom.json")) == []


def test_custom_token_counter_is_used_for_token_fields(tmp_path) -> None:
    """Configured token counter should drive prompt and response token counts."""
    emitter = PBOMEmitter(
        application_id="test",
        output_dir=tmp_path,
        sdk_version="0.1.0",
        token_counter=lambda text: 42,
    )

    with emitter.commit("sys", "user") as ctx:
        record = ctx.complete(model_id="openai/gpt-4o", response_text="resp")

    assert record.prompt.raw_content.system_prompt_token_count == 42
    assert record.prompt.raw_content.total_input_token_count == 84
    assert record.response.response_token_count == 42


def test_api1_total_latency_is_measured(tmp_path) -> None:
    """API 1 should measure total latency across context lifetime."""
    emitter = PBOMEmitter(
        application_id="test", output_dir=tmp_path, sdk_version="0.1.0"
    )

    with emitter.commit("sys", "user") as ctx:
        time.sleep(0.01)
        record = ctx.complete(model_id="openai/gpt-4o", response_text="resp")

    assert record.telemetry.total_latency_ms is not None
    assert record.telemetry.total_latency_ms >= 10


def test_complete_without_enter_raises_invalid_commitment_error(tmp_path) -> None:
    """Calling complete without entering context should fail loudly."""
    emitter = PBOMEmitter(
        application_id="test", output_dir=tmp_path, sdk_version="0.1.0"
    )
    context = emitter.commit("sys", "user")

    with pytest.raises(InvalidCommitmentError):
        context.complete(model_id="openai/gpt-4o", response_text="resp")


def test_complete_called_twice_raises_invalid_commitment_error(tmp_path) -> None:
    """complete() should only be allowed once per commitment context."""
    emitter = PBOMEmitter(
        application_id="test", output_dir=tmp_path, sdk_version="0.1.0"
    )
    with emitter.commit("sys", "user") as context:
        context.complete(model_id="openai/gpt-4o", response_text="resp")
        with pytest.raises(InvalidCommitmentError):
            context.complete(model_id="openai/gpt-4o", response_text="resp")


def test_emitter_restart_continues_sequence_and_hash_link(tmp_path) -> None:
    """New emitter instance should resume sequence and hash-link chain head."""
    first = PBOMEmitter(application_id="test", output_dir=tmp_path, sdk_version="0.1.0")
    with first.commit("sys-1", "user-1") as context:
        context.complete(model_id="openai/gpt-4o", response_text="resp-1")
    with first.commit("sys-2", "user-2") as context:
        context.complete(model_id="openai/gpt-4o", response_text="resp-2")

    second = PBOMEmitter(
        application_id="test", output_dir=tmp_path, sdk_version="0.1.0"
    )
    with second.commit("sys-3", "user-3") as context:
        record = context.complete(model_id="openai/gpt-4o", response_text="resp-3")

    payloads = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in tmp_path.glob("*.pbom.json")
    ]
    payloads.sort(key=lambda rec: rec["identity"]["chain_sequence_number"])
    second_payload = payloads[1]
    second_hash = compute_sha256(
        json.dumps(second_payload, sort_keys=True, separators=(",", ":"))
    )

    assert record.identity.chain_sequence_number == 3
    assert record.identity.previous_entry_hash == second_hash


def test_record_api_fingerprint_mode_omits_raw_text_fields(tmp_path) -> None:
    """Post-hoc record() in fingerprint mode should not persist raw text."""
    emitter = PBOMEmitter(
        application_id="test",
        output_dir=tmp_path,
        storage_mode="fingerprint",
        sdk_version="0.1.0",
    )

    record = emitter.record(
        system_prompt="sys prompt",
        user_prompt="user prompt",
        model_id="openai/gpt-4o",
        response_text="resp text",
    )

    assert record.prompt.raw_content.system_prompt_text is None
    assert record.prompt.raw_content.user_prompt_text is None
    assert record.response.response_text is None
    assert record.storage_mode == "fingerprint"


def test_full_prompt_hash_and_commitment_match_canonical_prompt_json(tmp_path) -> None:
    """Prompt and commitment hashes should use the same canonical prompt JSON."""
    emitter = PBOMEmitter(
        application_id="test",
        output_dir=tmp_path,
        storage_mode="forensic",
        sdk_version="0.1.0",
    )
    system_prompt = "system prompt"
    user_prompt = "user prompt"
    with emitter.commit(system_prompt, user_prompt) as context:
        record = context.complete(model_id="openai/gpt-4o", response_text="resp")

    canonical_prompt_json = json.dumps(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        sort_keys=True,
        separators=(",", ":"),
    )

    assert record.prompt.raw_content.full_prompt_hash == compute_sha256(
        canonical_prompt_json
    )
    assert record.commitment.commitment_hash == compute_sha256(
        canonical_prompt_json + record.commitment.nonce
    )


def test_emit_version_separation(tmp_path) -> None:
    """Emitted record must keep PBOM format version separate from package version."""
    from pbom import __version__

    emitter = PBOMEmitter(
        application_id="test", output_dir=tmp_path, sdk_version="0.1.0"
    )

    with emitter.commit("sys", "user") as ctx:
        record = ctx.complete(model_id="openai/gpt-4o", response_text="resp")

    assert record.identity.pbom_version == "1.0.0"
    assert record.identity.pbom_version != __version__

    files = sorted(tmp_path.glob("*.pbom.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["identity"]["pbom_version"] == "1.0.0"


def test_emit_jsonld_envelope(tmp_path) -> None:
    """Fresh emitted records should carry the expected JSON-LD envelope values."""
    emitter = PBOMEmitter(
        application_id="test", output_dir=tmp_path, sdk_version="0.1.0"
    )

    with emitter.commit("sys", "user") as ctx:
        record = ctx.complete(model_id="openai/gpt-4o", response_text="resp")

    payload = record.to_json_dict()

    assert payload["@context"] == "https://pbom.org/context/v1"
    assert payload["@id"].startswith("urn:uuid:")
    assert payload["@type"] == "PBOMRecord"


def test_emit_inference_params_default_none(tmp_path) -> None:
    """Unset optional inference params should serialize as present null fields."""
    emitter = PBOMEmitter(
        application_id="test", output_dir=tmp_path, sdk_version="0.1.0"
    )

    with emitter.commit("sys", "user") as ctx:
        record = ctx.complete(
            model_id="openai/gpt-4o",
            response_text="resp",
        )

    payload = record.to_json_dict()
    inference = payload["inference"]

    assert "temperature" in inference and inference["temperature"] is None
    assert "max_tokens" in inference and inference["max_tokens"] is None
    assert "streaming" in inference and inference["streaming"] is None
    assert "context_window_max" in inference and inference["context_window_max"] is None
    assert (
        "context_utilization_pct" in inference
        and inference["context_utilization_pct"] is None
    )


def test_emit_model_fields_not_parsed(tmp_path) -> None:
    """Emitter must not infer model_family/provider from model_id."""
    emitter = PBOMEmitter(
        application_id="test", output_dir=tmp_path, sdk_version="0.1.0"
    )

    with emitter.commit("sys", "user") as ctx:
        record = ctx.complete(
            model_id="openai/gpt-4o",
            response_text="resp",
        )

    assert record.inference.model_family is None
    assert record.inference.model_provider is None
