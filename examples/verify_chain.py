"""Validate PBOM chain integrity and commitment stats.

Run basic_usage.py first to generate records.
"""

from __future__ import annotations

from pathlib import Path

from pbom import validate_chain

pbom_dir = Path(".pbom")
if not pbom_dir.exists() or not any(pbom_dir.glob("*.pbom.json")):
    print("No PBOM records found. Run examples/basic_usage.py first.")
    raise SystemExit(0)

result = validate_chain(pbom_dir)
stats = result.commitment_results

print(f"total records: {result.total_records}")
print(f"chain valid: {result.is_valid}")
print(
    "commitments: "
    f"verified={stats['verified']} "
    f"unverifiable={stats['unverifiable']} "
    f"failed={stats['failed']}"
)

# Example broken output:
# total records: 2
# chain valid: False
# commitments: verified=1 unverifiable=1 failed=0

# CI-style check:
# sys.exit(0 if result.is_valid else 1)
