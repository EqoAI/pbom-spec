"""Integration regression tests for end-to-end chain behavior."""

from __future__ import annotations

import json

from pbom.chain import ChainState
from pbom.emitter import PBOMEmitter
from pbom.hashing import compute_sha256
from pbom.validator import validate_chain


def _sorted_record_payloads(directory) -> list[dict]:
    """Return parsed PBOM records sorted by chain sequence number."""
    payloads = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in directory.glob("*.pbom.json")
    ]
    payloads.sort(key=lambda rec: rec["identity"]["chain_sequence_number"])
    return payloads


def _canonical_hash(payload: dict) -> str:
    """Return canonical hash for a record payload."""
    return compute_sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def test_emit_validate_restart_roundtrip_preserves_chain(tmp_path) -> None:
    """Emitting across emitter restarts should preserve a valid contiguous chain."""
    first_emitter = PBOMEmitter(
        application_id="integration-test",
        output_dir=tmp_path,
        sdk_version="0.1.0",
    )
    with first_emitter.commit("sys-1", "user-1") as ctx:
        ctx.complete(model_id="test/model", response_text="resp-1")
    with first_emitter.commit("sys-2", "user-2") as ctx:
        ctx.complete(model_id="test/model", response_text="resp-2")

    # Simulate cold process restart by constructing a new emitter.
    second_emitter = PBOMEmitter(
        application_id="integration-test",
        output_dir=tmp_path,
        sdk_version="0.1.0",
    )
    with second_emitter.commit("sys-3", "user-3") as ctx:
        third = ctx.complete(model_id="test/model", response_text="resp-3")

    assert third.identity.chain_sequence_number == 3

    result = validate_chain(tmp_path)
    assert result.is_valid is True
    assert result.total_records == 3
    assert result.valid_links == 2


def test_second_record_previous_hash_matches_first_canonical_sha256(tmp_path) -> None:
    """Second record should store exact canonical hash of first record."""
    emitter = PBOMEmitter(
        application_id="integration-test", output_dir=tmp_path, sdk_version="0.1.0"
    )
    with emitter.commit("sys-1", "user-1") as ctx:
        ctx.complete(model_id="test/model", response_text="resp-1")
    with emitter.commit("sys-2", "user-2") as ctx:
        second = ctx.complete(model_id="test/model", response_text="resp-2")

    payloads = _sorted_record_payloads(tmp_path)
    first_hash = _canonical_hash(payloads[0])
    assert second.identity.previous_entry_hash == first_hash


def test_resume_from_and_validate_chain_agree_on_emitted_records(tmp_path) -> None:
    """Chain resume state and validator should agree on the same chain head."""
    emitter = PBOMEmitter(
        application_id="integration-test", output_dir=tmp_path, sdk_version="0.1.0"
    )
    for idx in range(1, 4):
        with emitter.commit(f"sys-{idx}", f"user-{idx}") as ctx:
            ctx.complete(model_id="test/model", response_text=f"resp-{idx}")

    result = validate_chain(tmp_path)
    assert result.is_valid is True

    payloads = _sorted_record_payloads(tmp_path)
    highest = payloads[-1]
    expected_head_hash = _canonical_hash(highest)

    resumed = ChainState()
    resumed.resume_from(tmp_path)
    next_sequence, previous_hash = resumed.next_chain_position()

    assert next_sequence == highest["identity"]["chain_sequence_number"] + 1
    assert previous_hash == expected_head_hash
