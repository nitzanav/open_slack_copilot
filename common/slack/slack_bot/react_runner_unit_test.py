import pytest

from common.slack.slack_bot.react_runner import (
    NO_ACTION_TEXT,
    _format_failure_message,
)
from common.slack.slack_bot.thread_reply_confirmation import ReviseError


@pytest.mark.parametrize(
    ("trigger", "action", "expected"),
    [
        (None, None, "Failed to process request."),
        ("", "  ", "Failed to process request."),
        ("slash", None, "Failed to process: slash."),
        (None, "act", "Failed to process: act."),
        ("t1", "a1", "Failed to process: t1, a1."),
    ],
)
def test_format_failure_message(trigger, action, expected):
    assert _format_failure_message(trigger, action) == expected


def test_no_action_constant():
    assert NO_ACTION_TEXT == "No action taken."


def test_resolve_missing_anchor_channel_tail_ok():
    from common.slack.slack_bot.react_runner import _resolve_thread_messages
    from unittest.mock import patch

    with patch(
        "common.slack.slack_bot.react_runner.fetch_channel_tail_messages",
        return_value=[{"ts": "1"}],
    ) as mock_tail:
        out = _resolve_thread_messages(
            "C1", "", "channel_tail", None,
        )
    assert out == [{"ts": "1"}]
    mock_tail.assert_called_once_with("C1")


def test_resolve_missing_anchor_thread_raises():
    from common.slack.slack_bot.react_runner import _resolve_thread_messages

    with pytest.raises(ReviseError, match="Missing thread anchor"):
        _resolve_thread_messages("C1", "", "thread", None)
