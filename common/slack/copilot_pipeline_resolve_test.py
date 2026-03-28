from unittest.mock import patch

from common.slack.copilot_pipeline import (
    prepare_draft,
    resolve_copilot_slack_context,
    ThreadFetchError,
)
from common.tools.schedule_tool import SCHEDULE_PROMPT_TOOL
from common.tools.send_slack_pm import SEND_SLACK_PM_TOOL


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


class TestPrepareDraftExcludedTools:
    @patch("common.slack.copilot_pipeline.fetch_thread_messages")
    @patch("common.slack.copilot_pipeline.slack_rag")
    @patch("common.slack.copilot_pipeline.progressive_disclosure")
    @patch("common.slack.copilot_pipeline.llm_client")
    @patch("common.slack.copilot_pipeline.slack_api")
    def test_excluded_tools_omit_schedule_keep_others(
        self, mock_slack, mock_llm, mock_pd, mock_rag, mock_fetch,
    ):
        mock_pd.select_skills.return_value = []
        mock_pd.get_default_instruction.return_value = "default"
        mock_rag.is_ready.return_value = True
        mock_rag.query_channel.return_value = []
        mock_rag.missing_channels.return_value = []
        mock_rag.query_cross_channel.return_value = []
        mock_llm.agent_tool_loop.return_value = "ok"
        mock_fetch.return_value = [{"text": "x"}]

        prepare_draft(
            "C", "T1", "U1", "",
            excluded_tools=[SCHEDULE_PROMPT_TOOL],
        )
        tools_passed = mock_llm.agent_tool_loop.call_args[0][2]
        assert SCHEDULE_PROMPT_TOOL not in tools_passed
        assert SEND_SLACK_PM_TOOL in tools_passed
