"""SHA-256 hashing utilities for PBOM records.

This module exposes a single helper used across the package for all hashing
operations (prompt content, response content, commitments, and chain linking).
The contract is strict: input text is encoded as UTF-8 and hashed with SHA-256,
and the function returns the lowercase hexadecimal digest.
"""

from __future__ import annotations

import hashlib
import logging

logger = logging.getLogger("pbom")


def compute_sha256(text: str) -> str:
    """Return the lowercase SHA-256 hex digest of UTF-8 encoded text.

    Args:
        text: Input text to hash. Empty strings are valid.

    Returns:
        The 64-character lowercase hexadecimal SHA-256 digest.

    Raises:
        TypeError: If ``text`` is ``None``.
    """
    # Enforce a clear runtime error for ``None`` to avoid silent misuse.
    if text is None:
        raise TypeError("text must be a str, got None")

    # PBOM constitution requirement: SHA-256 over UTF-8 encoded bytes.
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
