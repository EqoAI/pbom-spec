"""Merkle-style chain state for PBOM records.

The chain is per-directory, not per-application. Multiple ``application_id``
values writing to the same ``.pbom/`` directory share one chain.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional

from .exceptions import ChainCorruptedError
from .hashing import compute_sha256

logger = logging.getLogger("pbom")


class ChainState:
    """Thread-safe in-memory chain state with strict on-disk resume checks."""

    def __init__(self) -> None:
        """Initialize empty chain state guarded by an internal lock."""
        self._lock = threading.Lock()
        self._previous_entry_hash: Optional[str] = None
        self._chain_sequence: int = 0

    def next_chain_position(self) -> tuple[int, Optional[str]]:
        """Return next sequence number and current previous-entry hash.

        All reads and writes of in-memory chain state happen under the lock.
        """
        with self._lock:
            self._chain_sequence += 1
            return self._chain_sequence, self._previous_entry_hash

    def update_chain(self, canonical_json: str) -> str:
        """Update chain with canonical JSON and return its SHA-256 hash."""
        new_hash = compute_sha256(canonical_json)
        with self._lock:
            self._previous_entry_hash = new_hash
        return new_hash

    def resume_from(self, directory: Path) -> None:
        """Resume chain state from ``*.pbom.json`` files with strict validation.

        Validation performed:
        - Records must parse as JSON and include ``identity.chain_sequence_number``
        - Sequence numbers must be unique and contiguous from 1..N
        - For each consecutive pair, hash(previous_record_canonical_json) must
          equal ``next.identity.previous_entry_hash``
        """
        record_files = sorted(directory.glob("*.pbom.json"))
        if not record_files:
            self.reset()
            return

        parsed_records: list[tuple[int, str, str, str | None]] = []
        # tuple: (sequence, entry_id, canonical_json, previous_entry_hash)

        for record_path in record_files:
            try:
                raw_text = record_path.read_text(encoding="utf-8")
                record_data = json.loads(raw_text)
            except (OSError, json.JSONDecodeError) as exc:
                raise ChainCorruptedError(
                    "Failed to parse PBOM record during chain resume.",
                    entry_id=record_path.name,
                    details=str(exc),
                ) from exc

            identity = record_data.get("identity")
            if not isinstance(identity, dict):
                raise ChainCorruptedError(
                    "Record missing identity object during chain resume.",
                    entry_id=record_path.name,
                    details="identity must be an object",
                )

            sequence = identity.get("chain_sequence_number")
            if not isinstance(sequence, int):
                raise ChainCorruptedError(
                    "Record has invalid chain sequence number.",
                    entry_id=str(identity.get("entry_id") or record_path.name),
                    details="identity.chain_sequence_number must be an integer",
                )

            entry_id = str(identity.get("entry_id") or record_path.name)
            previous_entry_hash = identity.get("previous_entry_hash")
            if previous_entry_hash is not None and not isinstance(
                previous_entry_hash, str
            ):
                raise ChainCorruptedError(
                    "Record has invalid previous_entry_hash type.",
                    entry_id=entry_id,
                    details="identity.previous_entry_hash must be null or string",
                )

            canonical_json = json.dumps(
                record_data, sort_keys=True, separators=(",", ":")
            )
            parsed_records.append(
                (sequence, entry_id, canonical_json, previous_entry_hash)
            )

        parsed_records.sort(key=lambda item: item[0])

        seen_sequences: set[int] = set()
        for sequence, entry_id, _, _ in parsed_records:
            if sequence in seen_sequences:
                raise ChainCorruptedError(
                    "Duplicate chain sequence number detected.",
                    entry_id=entry_id,
                    details=f"duplicate chain_sequence_number={sequence}",
                )
            seen_sequences.add(sequence)

        expected_sequence = 1
        for sequence, entry_id, _, _ in parsed_records:
            if sequence != expected_sequence:
                raise ChainCorruptedError(
                    "Gap detected in chain sequence numbers.",
                    entry_id=entry_id,
                    details=(
                        f"expected chain_sequence_number={expected_sequence}, "
                        f"found {sequence}"
                    ),
                )
            expected_sequence += 1

        first_sequence, first_entry_id, _, first_previous_hash = parsed_records[0]
        if first_sequence != 1 or first_previous_hash is not None:
            raise ChainCorruptedError(
                "First record has invalid chain anchor.",
                entry_id=first_entry_id,
                details="sequence=1 must have previous_entry_hash=null",
            )

        for idx in range(len(parsed_records) - 1):
            seq, entry_id, canonical_json, _ = parsed_records[idx]
            next_seq, next_entry_id, _, next_previous_hash = parsed_records[idx + 1]
            expected_hash = compute_sha256(canonical_json)
            if next_previous_hash != expected_hash:
                raise ChainCorruptedError(
                    "Broken hash link between consecutive chain records.",
                    entry_id=next_entry_id,
                    details=(
                        f"expected previous_entry_hash from {entry_id} (seq={seq}) "
                        f"to match for seq={next_seq}"
                    ),
                )

        final_sequence, _, final_canonical_json, _ = parsed_records[-1]
        final_hash = compute_sha256(final_canonical_json)
        with self._lock:
            self._chain_sequence = final_sequence
            self._previous_entry_hash = final_hash

    def reset(self) -> None:
        """Reset in-memory chain state (primarily for tests)."""
        with self._lock:
            self._chain_sequence = 0
            self._previous_entry_hash = None


_DEFAULT_CHAIN_STATE = ChainState()


def next_chain_position() -> tuple[int, Optional[str]]:
    """Return the next chain sequence and previous hash from default state."""
    return _DEFAULT_CHAIN_STATE.next_chain_position()


def update_chain(canonical_json: str) -> str:
    """Update default chain state with canonical JSON and return new hash."""
    return _DEFAULT_CHAIN_STATE.update_chain(canonical_json)


def resume_from(directory: Path) -> None:
    """Resume default chain state from PBOM files in ``directory``."""
    _DEFAULT_CHAIN_STATE.resume_from(directory)


def reset() -> None:
    """Reset default chain state (primarily for tests)."""
    _DEFAULT_CHAIN_STATE.reset()
