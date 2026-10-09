"""PBOM chain and commitment validation utilities."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pbom._safe_io import read_record_text
from pbom._safe_log import describe_parse_error
from pbom.hashing import compute_sha256
from pbom.schema import PBOMRecord

logger = logging.getLogger("pbom")


@dataclass
class ValidationResult:
    """Structured validation output for chain and commitment checks.

    ``details``, ``unreadable_files``, and ``noncanonical_files`` contain
    strings derived from untrusted record files and file names. Callers must
    escape them before displaying (terminal, HTML, or logs).
    """

    total_records: int
    valid_links: int
    broken_links: list[dict[str, str | None]] = field(default_factory=list)
    sequence_gaps: list[tuple[int, int]] = field(default_factory=list)
    duplicate_sequences: list[int] = field(default_factory=list)
    unreadable_files: list[str] = field(default_factory=list)
    noncanonical_files: list[str] = field(default_factory=list)
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
    noncanonical_files: list[str] = []
    details: list[str] = []

    for record_path in record_files:
        record, noncanonical = _load_record(record_path)
        if record is None:
            path_str = str(record_path)
            unreadable_files.append(path_str)
            details.append(f"Unreadable file skipped during validation: {path_str}")
            continue
        if noncanonical:
            path_str = str(record_path)
            noncanonical_files.append(path_str)
            details.append(
                "Non-canonical record (unknown fields, duplicate keys, or type "
                f"coercion): {path_str}"
            )
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
        unreadable_files
        or noncanonical_files
        or duplicate_sequences
        or sequence_gaps
        or broken_links
    )

    return ValidationResult(
        total_records=len(parsed_records),
        valid_links=valid_links,
        broken_links=broken_links,
        sequence_gaps=sequence_gaps,
        duplicate_sequences=duplicate_sequences,
        unreadable_files=unreadable_files,
        noncanonical_files=noncanonical_files,
        commitment_results=commitment_results,
        is_valid=is_valid,
        details=details,
    )


def _pairs_hook_detect_duplicates(
    pairs: list[tuple[str, object]],
    *,
    duplicate_found: list[bool],
) -> dict[str, object]:
    """Build a dict like json.loads, but flag duplicate keys at this object depth.

    Nested objects each invoke the hook, so duplicates at any depth are caught.
    Last value wins (same as the default decoder) so model validation can proceed
    and the record still participates in link checks.
    """
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            duplicate_found[0] = True
        result[key] = value
    return result


def _canonical_json_bytes(payload: object) -> str:
    """Canonical JSON string for byte-for-byte content comparison."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _is_noncanonical_payload(
    raw_dict: dict[str, object],
    record: PBOMRecord,
    *,
    had_duplicate_keys: bool,
) -> bool:
    """True if on-disk JSON is not exactly the hashed record shape.

    Compares canonical JSON strings (not dict equality): Python treats
    ``1 == 1.0 == True``, which would hide type-coercion tampers. Parsing
    normalizes content (unknown fields dropped, duplicates collapsed, types
    coerced), so this check ensures the file contains exactly what was hashed.
    """
    if had_duplicate_keys:
        return True
    raw_canonical = _canonical_json_bytes(raw_dict)
    model_canonical = _canonical_json_bytes(record.to_json_dict())
    return raw_canonical != model_canonical


def _load_record(path: Path) -> tuple[Optional[PBOMRecord], bool]:
    """Load a record; return ``(record, is_noncanonical)``.

    ``(None, False)`` means the file was unreadable. A non-canonical file still
    returns the parsed model so link checks run unchanged. Parsing alone is not
    enough for tamper-evidence: pydantic drops unknown nested fields, collapses
    duplicate keys, and coerces types, so the file must match the hashed shape.
    """
    try:
        duplicate_found = [False]

        def _hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
            return _pairs_hook_detect_duplicates(
                pairs, duplicate_found=duplicate_found
            )

        raw_dict = json.loads(
            read_record_text(path),
            object_pairs_hook=_hook,
        )
        if not isinstance(raw_dict, dict):
            raise ValueError("PBOM record root must be a JSON object")
        record = PBOMRecord.model_validate(raw_dict)
        noncanonical = _is_noncanonical_payload(
            raw_dict, record, had_duplicate_keys=duplicate_found[0]
        )
        return record, noncanonical
    except (OSError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        # File may be corrupted or not valid PBOM JSON — skip it but
        # inform the caller so it can be reported in ValidationResult.
        # RecursionError: crafted deep nesting can exceed the JSON parser limit.
        logger.warning(
            "Failed to read PBOM record %r: %r",
            str(path),
            describe_parse_error(exc),
        )
        return None, False


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
