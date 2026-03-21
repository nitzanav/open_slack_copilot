from unittest.mock import patch

from common.slack.copilot_pipeline import (
    resolve_copilot_slack_context,
    ThreadFetchError,
)


class TestResolveCopilotSlackContext:
    @patch("common.slack.copilot_pipeline.fetch_channel_tail_messages")
    def test_channel_root_uses_tail(self, mock_tail):
        mock_tail.return_value = [{"ts": "1"}, {"ts": "2"}]
        anchor, msgs = resolve_copilot_slack_context("C1", {"ts": "99.0"})
        assert anchor == "99.0"
        assert msgs == [{"ts": "1"}, {"ts": "2"}]
        mock_tail.assert_called_once_with("C1")

    @patch("common.slack.copilot_pipeline.fetch_thread_messages")
    def test_thread_message_uses_replies(self, mock_fetch):
        mock_fetch.return_value = [{"text": "a"}]
        anchor, msgs = resolve_copilot_slack_context(
            "C1",
            {"ts": "2.0", "thread_ts": "1.0"},
        )
        assert anchor == "1.0"
        assert msgs == [{"text": "a"}]
        mock_fetch.assert_called_once_with("C1", "1.0")

    @patch("common.slack.copilot_pipeline.fetch_thread_messages")
    def test_thread_parent_propagates_thread_fetch_error(self, mock_fetch):
        mock_fetch.side_effect = ThreadFetchError("x")
        try:
            resolve_copilot_slack_context("C1", {"ts": "1.0", "thread_ts": "1.0"})
        except ThreadFetchError:
            pass
        else:
            raise AssertionError("expected ThreadFetchError")
