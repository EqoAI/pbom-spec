"""Tests for pbom.chain behavior and resume safety."""

import json

import pytest

from pbom.chain import ChainState
from pbom.emitter import PBOMEmitter
from pbom.exceptions import ChainCorruptedError
from pbom.hashing import compute_sha256


def test_fresh_state_starts_at_sequence_one_with_no_previous_hash() -> None:
    """A new ChainState should begin at sequence 1 with no previous hash."""
    chain = ChainState()

    sequence, previous_hash = chain.next_chain_position()

    assert sequence == 1
    assert previous_hash is None


def test_next_position_increments_after_update_and_carries_previous_hash() -> None:
    """After update_chain, next position should increment and return that hash."""
    chain = ChainState()
    first_sequence, first_previous = chain.next_chain_position()
    assert first_sequence == 1
    assert first_previous is None

    canonical_json = '{"a":1}'
    expected_hash = compute_sha256(canonical_json)
    returned_hash = chain.update_chain(canonical_json)
    assert returned_hash == expected_hash

    second_sequence, second_previous = chain.next_chain_position()
    assert second_sequence == 2
    assert second_previous == expected_hash


def test_update_chain_returns_sha256_of_canonical_json() -> None:
    """update_chain should return the SHA-256 digest of provided canonical JSON."""
    chain = ChainState()
    canonical_json = '{"k":"v","n":2}'

    returned_hash = chain.update_chain(canonical_json)

    assert returned_hash == compute_sha256(canonical_json)


def test_multi_record_chain_tracks_sequence_and_previous_hash_correctly() -> None:
    """Each new position should reference hash of immediately previous record."""
    chain = ChainState()
    records = [
        '{"id":1}',
        '{"id":2}',
        '{"id":3}',
        '{"id":4}',
    ]

    expected_previous = None
    for idx, record_json in enumerate(records, start=1):
        sequence, previous_hash = chain.next_chain_position()
        assert sequence == idx
        assert previous_hash == expected_previous
        expected_previous = compute_sha256(record_json)
        chain.update_chain(record_json)


def test_reset_clears_chain_state() -> None:
    """reset should restore state to initial sequence and null previous hash."""
    chain = ChainState()
    chain.next_chain_position()
    chain.update_chain('{"x":1}')
    chain.next_chain_position()
    chain.update_chain('{"x":2}')

    chain.reset()
    sequence, previous_hash = chain.next_chain_position()

    assert sequence == 1
    assert previous_hash is None


def test_resume_from_disk_restores_last_sequence_and_previous_hash(tmp_path) -> None:
    """resume_from should restore chain head from real emitted PBOM files."""
    emitter = PBOMEmitter(
        application_id="chain-test",
        output_dir=tmp_path,
        sdk_version="0.1.0",
    )

    with emitter.commit("sys", "u1") as ctx:
        ctx.complete(model_id="test/model", response_text="r1")
    with emitter.commit("sys", "u2") as ctx:
        ctx.complete(model_id="test/model", response_text="r2")
    with emitter.commit("sys", "u3") as ctx:
        ctx.complete(model_id="test/model", response_text="r3")

    files = sorted(tmp_path.glob("*.pbom.json"))
    assert len(files) == 3

    parsed = [json.loads(path.read_text(encoding="utf-8")) for path in files]
    parsed.sort(key=lambda rec: rec["identity"]["chain_sequence_number"])
    highest = parsed[-1]
    expected_previous_hash = compute_sha256(
        json.dumps(highest, sort_keys=True, separators=(",", ":"))
    )
    expected_next_sequence = highest["identity"]["chain_sequence_number"] + 1

    resumed = ChainState()
    resumed.resume_from(tmp_path)
    next_sequence, previous_hash = resumed.next_chain_position()

    assert next_sequence == expected_next_sequence
    assert previous_hash == expected_previous_hash


def test_resume_detects_duplicate_sequence_numbers(tmp_path) -> None:
    """resume_from should raise ChainCorruptedError on duplicate sequence numbers."""
    record1 = {
        "identity": {
            "entry_id": "e1",
            "chain_sequence_number": 1,
            "previous_entry_hash": None,
        }
    }
    record2 = {
        "identity": {
            "entry_id": "e2",
            "chain_sequence_number": 1,
            "previous_entry_hash": None,
        }
    }
    (tmp_path / "a.pbom.json").write_text(
        json.dumps(record1, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    (tmp_path / "b.pbom.json").write_text(
        json.dumps(record2, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )

    chain = ChainState()
    with pytest.raises(ChainCorruptedError):
        chain.resume_from(tmp_path)


def test_resume_detects_sequence_gaps(tmp_path) -> None:
    """resume_from should raise ChainCorruptedError when sequence has gaps."""
    record1 = {
        "identity": {
            "entry_id": "e1",
            "chain_sequence_number": 1,
            "previous_entry_hash": None,
        }
    }
    record3 = {
        "identity": {
            "entry_id": "e3",
            "chain_sequence_number": 3,
            "previous_entry_hash": "x" * 64,
        }
    }
    (tmp_path / "a.pbom.json").write_text(
        json.dumps(record1, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    (tmp_path / "c.pbom.json").write_text(
        json.dumps(record3, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )

    chain = ChainState()
    with pytest.raises(ChainCorruptedError):
        chain.resume_from(tmp_path)


def test_resume_detects_broken_hash_links(tmp_path) -> None:
    """resume_from should raise ChainCorruptedError on invalid previous_entry_hash."""
    record1 = {
        "identity": {
            "entry_id": "e1",
            "chain_sequence_number": 1,
            "previous_entry_hash": None,
        }
    }
    record1_hash = compute_sha256(
        json.dumps(record1, sort_keys=True, separators=(",", ":"))
    )
    record2 = {
        "identity": {
            "entry_id": "e2",
            "chain_sequence_number": 2,
            "previous_entry_hash": record1_hash,
        }
    }

    (tmp_path / "one.pbom.json").write_text(
        json.dumps(record1, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    (tmp_path / "two.pbom.json").write_text(
        json.dumps(record2, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )

    # Tamper second record's link after writing.
    tampered = json.loads((tmp_path / "two.pbom.json").read_text(encoding="utf-8"))
    tampered["identity"]["previous_entry_hash"] = "0" * 64
    (tmp_path / "two.pbom.json").write_text(
        json.dumps(tampered, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )

    chain = ChainState()
    with pytest.raises(ChainCorruptedError):
        chain.resume_from(tmp_path)


def test_resume_raises_on_malformed_json(tmp_path) -> None:
    """resume_from should raise when a PBOM file is invalid JSON."""
    (tmp_path / "bad.pbom.json").write_text("{not-json", encoding="utf-8")

    chain = ChainState()
    with pytest.raises(ChainCorruptedError):
        chain.resume_from(tmp_path)


def test_resume_raises_on_missing_identity_object(tmp_path) -> None:
    """resume_from should raise when a record lacks identity object."""
    (tmp_path / "bad.pbom.json").write_text(
        json.dumps({"@type": "PBOMRecord"}, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    chain = ChainState()
    with pytest.raises(ChainCorruptedError):
        chain.resume_from(tmp_path)


def test_resume_raises_on_invalid_sequence_type(tmp_path) -> None:
    """resume_from should raise when sequence is not an integer."""
    payload = {
        "identity": {
            "entry_id": "e1",
            "chain_sequence_number": "1",
            "previous_entry_hash": None,
        }
    }
    (tmp_path / "bad.pbom.json").write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    chain = ChainState()
    with pytest.raises(ChainCorruptedError):
        chain.resume_from(tmp_path)


def test_resume_raises_when_first_record_sequence_is_not_one(tmp_path) -> None:
    """resume_from should reject chains whose first sequence is not 1."""
    payload = {
        "identity": {
            "entry_id": "e2",
            "chain_sequence_number": 2,
            "previous_entry_hash": "f" * 64,
        }
    }
    (tmp_path / "bad.pbom.json").write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    chain = ChainState()
    with pytest.raises(ChainCorruptedError):
        chain.resume_from(tmp_path)


def test_resume_empty_directory_resets_state(tmp_path) -> None:
    """resume_from on empty directory should reset chain state."""
    chain = ChainState()
    chain.next_chain_position()
    chain.update_chain('{"x":1}')

    chain.resume_from(tmp_path)
    sequence, previous_hash = chain.next_chain_position()

    assert sequence == 1
    assert previous_hash is None


def test_concurrent_emitters_do_not_duplicate_sequence(tmp_path) -> None:
    """Two independent emitters racing record() must not share a sequence.

    Before the claim-marker fix, each PBOMEmitter cached chain head at
    construction via resume_from(). After a barrier both called record(),
    both read the same stale (sequence, hash) from their private ChainState,
    and both wrote chain_sequence_number=1. record() itself did not raise;
    the duplicate only appeared on a later resume_from() of the directory.
    This test fails on that outcome: duplicate sequences on disk and/or
    ChainCorruptedError from a fresh resume_from().
    """
    import threading

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def worker(worker_id: int) -> None:
        try:
            emitter = PBOMEmitter(
                application_id=f"race-{worker_id}",
                output_dir=tmp_path,
                sdk_version="0.1.0",
            )
            barrier.wait()
            emitter.record(
                system_prompt="sys",
                user_prompt=f"user-{worker_id}",
                model_id="test/model",
                response_text=f"response-{worker_id}",
            )
        except BaseException as exc:  # noqa: BLE001 — collect any failure
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(1,)),
        threading.Thread(target=worker, args=(2,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == [], f"emitter record() raised: {errors!r}"

    files = sorted(tmp_path.glob("*.pbom.json"))
    assert len(files) == 2

    sequences = []
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        sequences.append(payload["identity"]["chain_sequence_number"])

    assert sorted(sequences) == [1, 2], f"duplicate or missing sequences: {sequences}"

    # Fresh scan must accept the directory (no duplicate / gap / broken link).
    ChainState().resume_from(tmp_path)
