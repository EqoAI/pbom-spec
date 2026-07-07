"""PBOM chain and commitment validation utilities."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pbom.hashing import compute_sha256
from pbom.schema import PBOMRecord

logger = logging.getLogger("pbom")


@dataclass
class ValidationResult:
    """Structured validation output for chain and commitment checks."""

    total_records: int
    valid_links: int
    broken_links: list[dict[str, str | None]] = field(default_factory=list)
    sequence_gaps: list[tuple[int, int]] = field(default_factory=list)
    duplicate_sequences: list[int] = field(default_factory=list)
    unreadable_files: list[str] = field(default_factory=list)
    commitment_results: dict[str, int] = field(
        default_factory=lambda: {"verified": 0, "unverifiable": 0, "failed": 0}
    )
    is_valid: bool = True
    details: list[str] = field(default_factory=list)


def validate_commitment(record: PBOMRecord) -> Optional[bool]:
    """Verify a single record's commitment. Returns None in fingerprint mode."""
    raw_content = record.prompt.raw_content
    system_prompt_text = raw_content.system_prompt_text
    user_prompt_text = raw_content.user_prompt_text

    if system_prompt_text is None or user_prompt_text is None:
        return None

    messages = [
        {"role": "system", "content": system_prompt_text},
        {"role": "user", "content": user_prompt_text},
    ]
    prompt_text = json.dumps(messages, sort_keys=True, separators=(",", ":"))

    nonce = record.commitment.nonce
    commitment_hash = record.commitment.commitment_hash
    if commitment_hash is None:
        return False

    recomputed = compute_sha256(prompt_text + nonce)
    return recomputed == commitment_hash


def validate_chain(directory: Path) -> ValidationResult:
    """Verify chain integrity across all records in a directory."""
    record_files = sorted(directory.glob("*.pbom.json"))
    if not record_files:
        return ValidationResult(total_records=0, valid_links=0, is_valid=True)

    parsed_records: list[PBOMRecord] = []
    unreadable_files: list[str] = []
    details: list[str] = []

    for record_path in record_files:
        record = _load_record(record_path)
        if record is None:
            path_str = str(record_path)
            unreadable_files.append(path_str)
            details.append(f"Unreadable file skipped during validation: {path_str}")
            continue
        parsed_records.append(record)

    parsed_records.sort(key=lambda rec: rec.identity.chain_sequence_number)
    sequences = [rec.identity.chain_sequence_number for rec in parsed_records]
    duplicate_sequences = _find_duplicate_sequences(sequences)
    sequence_gaps = _find_sequence_gaps(sequences)
    broken_links, valid_links = _validate_chain_links(parsed_records)

    commitment_results = {"verified": 0, "unverifiable": 0, "failed": 0}
    for record in parsed_records:
        commitment_validity = validate_commitment(record)
        if commitment_validity is None:
            commitment_results["unverifiable"] += 1
        elif commitment_validity:
            commitment_results["verified"] += 1
        else:
            commitment_results["failed"] += 1

    for sequence in duplicate_sequences:
        details.append(f"Duplicate chain sequence number detected: {sequence}")
    for gap_start, gap_end in sequence_gaps:
        details.append(
            f"Gap detected in chain sequence numbers: missing {gap_start}..{gap_end}"
        )
    for broken in broken_links:
        entry_id = broken["entry_id"]
        expected = broken["expected"]
        actual = broken["actual"]
        details.append(
            f"Broken chain link at entry {entry_id}: expected previous hash {expected}, got {actual}"
        )

    is_valid = not (
        unreadable_files or duplicate_sequences or sequence_gaps or broken_links
    )

    return ValidationResult(
        total_records=len(parsed_records),
        valid_links=valid_links,
        broken_links=broken_links,
        sequence_gaps=sequence_gaps,
        duplicate_sequences=duplicate_sequences,
        unreadable_files=unreadable_files,
        commitment_results=commitment_results,
        is_valid=is_valid,
        details=details,
    )


def _load_record(path: Path) -> Optional[PBOMRecord]:
    """Load and validate a PBOM record file, returning None on parse failure."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return PBOMRecord.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        # File may be corrupted or not valid PBOM JSON — skip it but
        # inform the caller so it can be reported in ValidationResult.
        logger.warning("Failed to read PBOM record %s: %s", path, exc)
        return None


def _canonical_record_hash(record: PBOMRecord) -> str:
    """Recompute canonical record hash independent of on-disk formatting."""
    canonical_json = json.dumps(
        record.model_dump(by_alias=True),
        sort_keys=True,
        separators=(",", ":"),
    )
    return compute_sha256(canonical_json)


def _find_duplicate_sequences(sequences: list[int]) -> list[int]:
    """Return duplicate sequence numbers in ascending order."""
    seen: set[int] = set()
    duplicates: set[int] = set()
    for sequence in sequences:
        if sequence in seen:
            duplicates.add(sequence)
        else:
            seen.add(sequence)
    return sorted(duplicates)


def _find_sequence_gaps(sequences: list[int]) -> list[tuple[int, int]]:
    """Return missing sequence ranges as (gap_start, gap_end)."""
    gaps: list[tuple[int, int]] = []
    for idx in range(1, len(sequences)):
        previous = sequences[idx - 1]
        current = sequences[idx]
        if current - previous > 1:
            gaps.append((previous + 1, current - 1))
    return gaps


def _validate_chain_links(
    records: list[PBOMRecord],
) -> tuple[list[dict[str, str | None]], int]:
    """Validate previous_entry_hash links for consecutive records."""
    broken_links: list[dict[str, str | None]] = []
    valid_links = 0
    if len(records) < 2:
        return broken_links, valid_links

    for idx in range(1, len(records)):
        previous = records[idx - 1]
        current = records[idx]
        expected_hash = _canonical_record_hash(previous)
        actual_hash = current.identity.previous_entry_hash
        if actual_hash != expected_hash:
            broken_links.append(
                {
                    "entry_id": current.identity.entry_id,
                    "expected": expected_hash,
                    "actual": actual_hash,
                }
            )
        else:
            valid_links += 1

    return broken_links, valid_links
