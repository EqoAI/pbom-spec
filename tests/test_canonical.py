"""Tests for canonical OpenAI-message conversion bridge."""

from __future__ import annotations

import pytest

from pbom.canonical import canonicalize_messages
from pbom.exceptions import UnsupportedMessageShapeError


def _assert_actionable_message(message: str) -> None:
    """Assert common actionable guidance in unsupported-shape errors."""
    assert message.startswith("canonicalize_messages:")
    assert "This shape is not supported in pbom v1.0.0." in message
    assert "PBOMEmitter.commit() or .record()" in message
    assert "See docs/canonical.md." in message


def test_canonicalize_messages_accepts_system_user_pair() -> None:
    """Canonical [system, user] shape returns corresponding tuple."""
    system_prompt, user_prompt = canonicalize_messages(
        [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Summarize this."},
        ]
    )

    assert system_prompt == "You are helpful."
    assert user_prompt == "Summarize this."


def test_canonicalize_messages_accepts_user_only_shape() -> None:
    """Single user message maps to empty system prompt and user content."""
    system_prompt, user_prompt = canonicalize_messages(
        [{"role": "user", "content": "Hello"}]
    )

    assert system_prompt == ""
    assert user_prompt == "Hello"


def test_canonicalize_messages_raises_type_error_for_non_list() -> None:
    """Non-list top-level input should raise TypeError."""
    with pytest.raises(TypeError):
        canonicalize_messages("not-a-list")  # type: ignore[arg-type]


def test_canonicalize_messages_rejects_empty_list() -> None:
    """Empty message list should raise UnsupportedMessageShapeError."""
    with pytest.raises(UnsupportedMessageShapeError) as exc_info:
        canonicalize_messages([])

    _assert_actionable_message(str(exc_info.value))


def test_canonicalize_messages_rejects_more_than_two_messages() -> None:
    """More than two messages should be rejected with message_count details."""
    with pytest.raises(UnsupportedMessageShapeError) as exc_info:
        canonicalize_messages(
            [
                {"role": "system", "content": "s"},
                {"role": "user", "content": "u"},
                {"role": "user", "content": "extra"},
            ]
        )

    _assert_actionable_message(str(exc_info.value))
    assert exc_info.value.shape_detail == {"message_count": 3}


def test_canonicalize_messages_raises_type_error_for_non_dict_message() -> None:
    """Non-dict message entries should raise TypeError."""
    with pytest.raises(TypeError):
        canonicalize_messages([{"role": "user", "content": "ok"}, "bad"])  # type: ignore[list-item]


def test_canonicalize_messages_rejects_unknown_keys() -> None:
    """Unknown message keys should be rejected."""
    with pytest.raises(UnsupportedMessageShapeError) as exc_info:
        canonicalize_messages([{"role": "user", "content": "ok", "name": "extra-key"}])

    _assert_actionable_message(str(exc_info.value))
    assert exc_info.value.shape_detail == {"unknown_keys": ["name"]}


def test_canonicalize_messages_rejects_missing_role() -> None:
    """Missing role key should be rejected."""
    with pytest.raises(UnsupportedMessageShapeError) as exc_info:
        canonicalize_messages([{"content": "ok"}])

    _assert_actionable_message(str(exc_info.value))


def test_canonicalize_messages_rejects_missing_content() -> None:
    """Missing content key should be rejected."""
    with pytest.raises(UnsupportedMessageShapeError) as exc_info:
        canonicalize_messages([{"role": "user"}])

    _assert_actionable_message(str(exc_info.value))


def test_canonicalize_messages_rejects_unsupported_role_with_detail() -> None:
    """Unsupported roles (assistant/tool/function/etc.) should include role detail."""
    with pytest.raises(UnsupportedMessageShapeError) as exc_info:
        canonicalize_messages([{"role": "assistant", "content": "hi"}])

    _assert_actionable_message(str(exc_info.value))
    assert exc_info.value.shape_detail == {"role": "assistant"}


def test_canonicalize_messages_rejects_non_string_content_with_detail() -> None:
    """Non-string content should be rejected with content_type detail."""
    with pytest.raises(UnsupportedMessageShapeError) as exc_info:
        canonicalize_messages([{"role": "user", "content": ["text-part"]}])

    _assert_actionable_message(str(exc_info.value))
    assert exc_info.value.shape_detail == {"content_type": "list"}


def test_canonicalize_messages_rejects_single_system_only_shape() -> None:
    """Single-message shape must be user-only; system-only is unsupported."""
    with pytest.raises(UnsupportedMessageShapeError) as exc_info:
        canonicalize_messages([{"role": "system", "content": "sys-only"}])

    _assert_actionable_message(str(exc_info.value))


@pytest.mark.parametrize(
    "messages",
    [
        [{"role": "user", "content": "u"}, {"role": "system", "content": "s"}],
        [{"role": "system", "content": "s1"}, {"role": "system", "content": "s2"}],
        [{"role": "user", "content": "u1"}, {"role": "user", "content": "u2"}],
    ],
)
def test_canonicalize_messages_rejects_invalid_two_message_order_or_roles(
    messages: list[dict[str, str]],
) -> None:
    """Any two-message shape other than [system, user] should be rejected."""
    with pytest.raises(UnsupportedMessageShapeError) as exc_info:
        canonicalize_messages(messages)

    _assert_actionable_message(str(exc_info.value))
    assert exc_info.value.shape_detail == {
        "roles": [messages[0]["role"], messages[1]["role"]]
    }
