"""Tests for pbom.hashing utilities."""

import pytest

from pbom.hashing import compute_sha256


def test_compute_sha256_simple_string_matches_expected_digest() -> None:
    """Hashing a known string should match its known SHA-256 digest."""
    assert (
        compute_sha256("hello")
        == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )


def test_compute_sha256_empty_string_is_valid() -> None:
    """Empty string is valid input and returns SHA-256 of empty bytes."""
    assert (
        compute_sha256("")
        == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_compute_sha256_is_consistent_for_same_input() -> None:
    """Repeated hashing of the same input should always produce same digest."""
    value = "repeatable-input"
    first = compute_sha256(value)
    second = compute_sha256(value)
    third = compute_sha256(value)

    assert first == second == third


def test_compute_sha256_none_raises_type_error() -> None:
    """None is invalid input and should raise TypeError."""
    with pytest.raises(TypeError):
        compute_sha256(None)  # type: ignore[arg-type]
