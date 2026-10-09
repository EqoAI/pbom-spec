"""Safe formatting helpers for log messages involving untrusted PBOM input."""

from __future__ import annotations

from pydantic import ValidationError


def describe_parse_error(exc: BaseException) -> str:
    """Summarize a parse/validate failure without leaking input values.

    Record files under ``.pbom/`` are attacker-controlled (spec §12). Pydantic
    ``ValidationError`` messages normally include the rejected input, which can
    contain forensic-mode prompt text. This helper keeps only error locations
    and types so warnings and CI logs stay free of raw field values.
    """
    if isinstance(exc, ValidationError):
        parts: list[str] = []
        for err in exc.errors(include_input=False):
            loc = ".".join(str(item) for item in err.get("loc", ()))
            err_type = err.get("type", "unknown")
            parts.append(f"{loc} ({err_type})")
        return f"ValidationError: {exc.error_count()} error(s): " + ", ".join(parts)
    return f"{type(exc).__name__}: {exc}"
