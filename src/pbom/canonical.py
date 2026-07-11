"""Canonical message-shape bridge for PBOM emitter APIs.

This module provides one blessed helper for converting OpenAI-style message
lists into the two-field ``(system_prompt, user_prompt)`` tuple that
``PBOMEmitter.commit()`` and ``PBOMEmitter.record()`` require.

It exists because adopters (including cold agents instrumenting existing call
sites) independently invented their own message-bridging functions, which led
to inconsistent prompt canonicalization and non-comparable hashes across
implementations. Centralizing the conversion here ensures one canonical bridge
in the OSS package.

The v1.0.0 implementation is intentionally narrow and supports only a small
set of input shapes. Multi-turn conversations, tool calls, and non-string
content are explicitly deferred to a future version and will evolve based on
adopter feedback.

Versioning note: PBOM OSS follows semantic versioning. Supported input shapes
for this helper may expand in v1.x minor releases, but the output semantics
(the meaning of the returned ``(system_prompt, user_prompt)`` tuple) remain
stable within v1.x.
"""

from __future__ import annotations

import logging

from .exceptions import UnsupportedMessageShapeError

logger = logging.getLogger("pbom")


def canonicalize_messages(messages: list[dict]) -> tuple[str, str]:
    """Convert an OpenAI-style message list to (system_prompt, user_prompt).

    Accepted shapes (v1.0.0):
      [{"role": "system", "content": "<str>"},
       {"role": "user", "content": "<str>"}]
        -> ("<system content>", "<user content>")

      [{"role": "user", "content": "<str>"}]
        -> ("", "<user content>")

    Rejected shapes (raise UnsupportedMessageShapeError):
      - Any list with more than one message per role
      - Any list containing assistant, tool, or function messages
      - Any message whose content is not a string (e.g., list of
        content parts, images, tool calls)
      - Any message with unknown keys beyond "role" and "content"
      - Empty list
      - Messages in the wrong order (user before system)

    Multi-turn support, tool calls, and content-parts are deferred to
    a future version. See the module docstring for context.

    Args:
        messages: OpenAI-style message list.

    Returns:
        (system_prompt, user_prompt) tuple of strings. system_prompt
        may be the empty string if no system message was provided.

    Raises:
        UnsupportedMessageShapeError: if the input does not match one
        of the accepted shapes above. The error message names the
        specific reason for rejection.
        TypeError: if messages is not a list, or a message is not a
            dict.
    """

    def _unsupported(
        specific_reason: str,
        *,
        shape_detail: dict[str, object] | None = None,
    ) -> UnsupportedMessageShapeError:
        return UnsupportedMessageShapeError(
            (
                "canonicalize_messages: "
                f"{specific_reason}. "
                "This shape is not supported in pbom v1.0.0. "
                "For multi-turn conversations, tool calls, or non-string content, "
                "concatenate the relevant content into a single string and pass "
                "it directly to PBOMEmitter.commit() or .record(). "
                "See docs/canonical.md."
            ),
            shape_detail=shape_detail,
        )

    # Top-level type and cardinality checks.
    if not isinstance(messages, list):
        raise TypeError(
            f"canonicalize_messages: messages must be a list, got {type(messages).__name__}"
        )
    if len(messages) == 0:
        raise _unsupported("empty message list")
    if len(messages) > 2:
        raise _unsupported(
            "message list has more than two items",
            shape_detail={"message_count": len(messages)},
        )

    # Per-message structural validation.
    validated: list[dict[str, str]] = []
    for idx, msg in enumerate(messages):
        if not isinstance(msg, dict):
            raise TypeError(
                "canonicalize_messages: each message must be a dict, "
                f"got {type(msg).__name__} at index {idx}"
            )

        unknown_keys = set(msg.keys()) - {"role", "content"}
        if unknown_keys:
            raise _unsupported(
                f"message at index {idx} contains unknown keys {sorted(unknown_keys)}",
                shape_detail={"unknown_keys": sorted(unknown_keys)},
            )

        if "role" not in msg:
            raise _unsupported(f"message at index {idx} is missing required key 'role'")

        if "content" not in msg:
            raise _unsupported(
                f"message at index {idx} is missing required key 'content'"
            )

        role = msg["role"]
        content = msg["content"]
        if role not in {"system", "user"}:
            raise _unsupported(
                f"message at index {idx} has unsupported role {role!r}",
                shape_detail={"role": role},
            )
        if not isinstance(content, str):
            raise _unsupported(
                f"message at index {idx} has non-string content",
                shape_detail={"content_type": type(content).__name__},
            )

        validated.append({"role": role, "content": content})

    # Shape-specific acceptance/rejection.
    if len(validated) == 1:
        only = validated[0]
        if only["role"] != "user":
            raise _unsupported("single-message shape must be a user message")
        return "", only["content"]

    first, second = validated
    if first["role"] == "system" and second["role"] == "user":
        return first["content"], second["content"]

    # Any other two-message combination is rejected:
    # [user, system], [system, system], [user, user].
    raise _unsupported(
        "two-message shape must be exactly [system, user] in that order",
        shape_detail={"roles": [first["role"], second["role"]]},
    )
