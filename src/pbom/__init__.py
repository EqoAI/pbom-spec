"""Public API surface for the PBOM package."""

from pbom.emitter import PBOMEmitter
from pbom.exceptions import (
    ChainCorruptedError,
    InvalidCommitmentError,
    PBOMError,
    SchemaValidationError,
)
from pbom.schema import PBOMRecord
from pbom.validator import ValidationResult, validate_chain, validate_commitment

__version__ = "0.1.0"

__all__ = [
    "ChainCorruptedError",
    "InvalidCommitmentError",
    "PBOMEmitter",
    "PBOMError",
    "PBOMRecord",
    "SchemaValidationError",
    "ValidationResult",
    "__version__",
    "validate_chain",
    "validate_commitment",
]
