"""Basic PBOM usage with pre-inference commitments."""

from __future__ import annotations

import shutil
from pathlib import Path

from pbom import PBOMEmitter

# Start clean on every run so chain state and files stay consistent.
shutil.rmtree(".pbom", ignore_errors=True)

# Create an emitter that writes records into .pbom/ by default.
emitter = PBOMEmitter(application_id="example-agent")

# Simulate two LLM interactions (mock responses, no network calls).
for system_prompt, user_prompt, mock_response in [
    ("You are helpful.", "Summarize this PR.", "This PR adds validation tests."),
    ("You are helpful.", "List security concerns.", "No high-risk issues found."),
]:
    # Preferred API: create commitment before "inference", complete afterward.
    with emitter.commit(system_prompt, user_prompt) as commitment:
        record = commitment.complete(
            model_id="openai/gpt-4o",
            response_text=mock_response,
        )

    # Record files are named from entry_id under .pbom/.
    record_path = Path(".pbom") / f"{record.identity.entry_id}.pbom.json"
    print(f"entry_id: {record.identity.entry_id}")
    print(f"file: {record_path}")
    print(f"sequence: {record.identity.chain_sequence_number}")
    print("-" * 40)
