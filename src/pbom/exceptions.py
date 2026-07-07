"""Custom exception types for the PBOM package.

These exceptions provide clear, domain-specific failure modes for commitment
validation, chain integrity checks, and schema validation.
"""

from __future__ import annotations


class PBOMError(Exception):
    """Base exception for all PBOM package errors."""

    def __init__(self, message: str) -> None:
        """Initialize the exception with a human-readable message."""
        super().__init__(message)


class InvalidCommitmentError(PBOMError):
    """Raised when commitment data is invalid or cannot be verified."""

    def __init__(self, message: str) -> None:
        """Initialize the exception with a commitment validation message."""
        super().__init__(message)


class ChainCorruptedError(PBOMError):
    """Raised when PBOM chain integrity checks detect corruption or mismatch."""

    def __init__(
        self,
        message: str,
        *,
        entry_id: str | None = None,
        details: str | None = None,
    ) -> None:
        """Initialize the exception with optional chain diagnostic context."""
        super().__init__(message)
        self.entry_id = entry_id
        self.details = details


class SchemaValidationError(PBOMError):
    """Raised when a record fails PBOM schema validation."""

    def __init__(self, message: str) -> None:
        """Initialize the exception with a schema validation message."""
        super().__init__(message)
