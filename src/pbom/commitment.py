"""PBOM cryptographic commitment scheme.

This module creates, reveals, and verifies commitments over canonical prompt
content using SHA-256. It supports both pre-inference and post-hoc commitment
types while preserving strict timestamp ordering requirements.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .exceptions import InvalidCommitmentError
from .hashing import compute_sha256

logger = logging.getLogger("pbom")


class Commitment(BaseModel):
    """Represents a prompt commitment and its lifecycle state."""

    nonce: str
    commitment_hash: str
    prompt_text: str
    commitment_ts: int
    nonce_revealed_ts: Optional[int] = None
    commitment_type: Literal["pre_inference", "post_hoc"]
    verified: bool = Field(default=False)


def create_commitment(
    system_prompt: str, user_prompt: str, commitment_type: str
) -> Commitment:
    """Create a new commitment from canonical prompt JSON and a random nonce."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    prompt_text = json.dumps(messages, sort_keys=True, separators=(",", ":"))
    nonce = os.urandom(16).hex()
    commitment_hash = compute_sha256(prompt_text + nonce)
    commitment_ts = int(time.time() * 1000)

    return Commitment(
        nonce=nonce,
        commitment_hash=commitment_hash,
        prompt_text=prompt_text,
        commitment_ts=commitment_ts,
        nonce_revealed_ts=None,
        commitment_type=commitment_type,
        verified=False,
    )


def reveal_commitment(commitment: Commitment) -> Commitment:
    """Set reveal timestamp and enforce strict commit-before-reveal ordering."""

    nonce_revealed_ts = int(time.time() * 1000)
    if commitment.commitment_ts >= nonce_revealed_ts:
        raise InvalidCommitmentError(
            "Commitment timestamp must be strictly less than reveal timestamp."
        )

    commitment.nonce_revealed_ts = nonce_revealed_ts
    return commitment


def verify_commitment(commitment: Commitment) -> bool:
    """Verify commitment hash by recomputing SHA-256(prompt_text + nonce)."""

    recomputed = compute_sha256(commitment.prompt_text + commitment.nonce)
    is_verified = recomputed == commitment.commitment_hash
    commitment.verified = is_verified
    return is_verified
