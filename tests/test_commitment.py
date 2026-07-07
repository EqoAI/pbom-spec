"""Tests for pbom.commitment lifecycle behavior."""

import re
import time
import unittest.mock

import pytest

from pbom.commitment import create_commitment, reveal_commitment, verify_commitment
from pbom.exceptions import InvalidCommitmentError


def test_create_commitment_basics() -> None:
    """create_commitment should populate expected core fields."""
    commitment = create_commitment(
        "You are a reviewer.",
        "Check this function.",
        "pre_inference",
    )

    assert commitment.nonce is not None
    assert re.fullmatch(r"[0-9a-f]{32}", commitment.nonce)
    assert commitment.commitment_hash is not None
    assert re.fullmatch(r"[0-9a-f]{64}", commitment.commitment_hash)
    assert commitment.commitment_ts > 0
    assert commitment.nonce_revealed_ts is None
    assert commitment.commitment_type == "pre_inference"


def test_reveal_sets_timestamp_strictly_greater_than_commitment_ts() -> None:
    """reveal_commitment should set reveal timestamp strictly after commitment timestamp."""
    commitment = create_commitment(
        "System",
        "User",
        "pre_inference",
    )
    time.sleep(0.001)

    revealed = reveal_commitment(commitment)

    assert revealed.nonce_revealed_ts is not None
    assert revealed.nonce_revealed_ts > revealed.commitment_ts


def test_verify_succeeds_on_untampered_commitment() -> None:
    """verify_commitment should return True when nothing was altered."""
    commitment = create_commitment(
        "System",
        "User",
        "pre_inference",
    )
    time.sleep(0.001)
    reveal_commitment(commitment)

    assert verify_commitment(commitment) is True


def test_verify_fails_on_tampered_nonce() -> None:
    """verify_commitment should return False if nonce is modified."""
    commitment = create_commitment(
        "System",
        "User",
        "pre_inference",
    )
    time.sleep(0.001)
    reveal_commitment(commitment)

    commitment.nonce = "0" * 32

    assert verify_commitment(commitment) is False


def test_verify_fails_on_tampered_prompt_text() -> None:
    """verify_commitment should return False if prompt text is modified."""
    commitment = create_commitment(
        "System",
        "User",
        "pre_inference",
    )
    time.sleep(0.001)
    reveal_commitment(commitment)

    commitment.prompt_text = '{"tampered":true}'

    assert verify_commitment(commitment) is False


def test_reveal_raises_on_equal_or_inverted_timestamps() -> None:
    """reveal_commitment should raise InvalidCommitmentError when ordering is invalid."""
    commitment = create_commitment(
        "System",
        "User",
        "pre_inference",
    )
    commitment.commitment_ts = int(time.time() * 1000) + 10_000

    with pytest.raises(InvalidCommitmentError):
        reveal_commitment(commitment)


def test_reveal_raises_on_equal_timestamps() -> None:
    """reveal_commitment should raise when commitment_ts equals reveal time."""
    commitment = create_commitment("System", "User", "pre_inference")
    fixed_ts = commitment.commitment_ts
    with unittest.mock.patch("pbom.commitment.time") as mock_time:
        mock_time.time.return_value = fixed_ts / 1000.0
        with pytest.raises(InvalidCommitmentError):
            reveal_commitment(commitment)


@pytest.mark.parametrize("commitment_type", ["pre_inference", "post_hoc"])
def test_both_commitment_types_create_reveal_and_verify(commitment_type: str) -> None:
    """Both commitment types should support normal create→reveal→verify flow."""
    commitment = create_commitment(
        "System prompt",
        "User prompt",
        commitment_type,
    )
    time.sleep(0.001)
    reveal_commitment(commitment)

    assert verify_commitment(commitment) is True
    assert commitment.commitment_type == commitment_type
