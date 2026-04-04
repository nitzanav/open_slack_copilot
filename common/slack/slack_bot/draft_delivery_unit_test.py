import pytest

from common.slack.slack_bot.draft_delivery import (
    NO_ACTION_DRAFT_TEXT,
    DraftReviseError,
    format_prepare_failure_message,
)


@pytest.mark.parametrize(
    ("trigger", "action", "expected"),
    [
        (None, None, "Failed to process draft."),
        ("", "  ", "Failed to process draft."),
        ("slash", None, "Failed to process: slash."),
        (None, "act", "Failed to process: act."),
        ("t1", "a1", "Failed to process: t1, a1."),
    ],
)
def test_format_prepare_failure_message(trigger, action, expected):
    assert format_prepare_failure_message(trigger, action) == expected


def test_no_action_constant():
    assert NO_ACTION_DRAFT_TEXT == "No action taken."


def test_resolve_missing_anchor_channel_tail_ok():
    from common.slack.slack_bot.draft_delivery import _resolve_thread_messages_when_needed
    from unittest.mock import patch

    with patch(
        "common.slack.slack_bot.draft_delivery.fetch_channel_tail_messages",
        return_value=[{"ts": "1"}],
    ) as mock_tail:
        out = _resolve_thread_messages_when_needed(
            "C1", "", "channel_tail", None,
        )
    assert out == [{"ts": "1"}]
    mock_tail.assert_called_once_with("C1")


def test_resolve_missing_anchor_thread_raises():
    from common.slack.slack_bot.draft_delivery import _resolve_thread_messages_when_needed

    with pytest.raises(DraftReviseError, match="Missing thread anchor"):
        _resolve_thread_messages_when_needed("C1", "", "thread", None)
