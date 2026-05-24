from unittest.mock import patch

from common.llm.llm_client.llm_client import AgentToolLoopResult
from common.slack.copilot_pipeline import (
    build_rag_query_text,
    run_react_loop,
    resolve_copilot_slack_context,
    ThreadFetchError,
)
from common.tools.list_usergroup_members import LIST_USERGROUP_MEMBERS_TOOL
from common.tools.list_users import LIST_USERS_TOOL
from common.tools.schedule_tool import SCHEDULE_PROMPT_TOOL
from common.tools.send_ephemeral_message import SEND_EPHEMERAL_MESSAGE_TOOL
from common.tools.send_dm_as_app import SEND_DM_AS_APP_TOOL
from common.tools.send_thread_reply_as_app import SEND_THREAD_REPLY_AS_APP_TOOL
from common.tools.send_thread_reply_on_behalf_of_requester import (
    SEND_THREAD_REPLY_ON_BEHALF_OF_REQUESTER_TOOL,
)


class TestBuildRagQueryText:
    def test_channel_tail_omits_background(self):
        tail = [{"text": "join notice"}, {"text": "automation bot spam"}]
        q = build_rag_query_text(
            anchor_message_text="make test fails",
            user_text='user asked to trigger skill "Draft thread reply".',
            thread_messages=tail,
            context_kind="channel_tail",
        )
        assert q.count("make test fails") == 3
        assert q.count('user asked to trigger skill "Draft thread reply".') == 2
        assert "join notice" not in q
        assert "automation bot spam" not in q

    def test_thread_includes_background_once(self):
        thread = [{"text": "prior"}, {"text": "latest"}]
        q = build_rag_query_text(
            anchor_message_text="anchor msg",
            user_text="please draft",
            thread_messages=thread,
            context_kind="thread",
        )
        assert q.count("anchor msg") == 3
        assert q.count("please draft") == 2
        assert q.endswith("prior latest")

    def test_empty_anchor_falls_back_to_instruction(self):
        q = build_rag_query_text(
            anchor_message_text=None,
            user_text="only instruction",
            thread_messages=[],
            context_kind="channel_tail",
        )
        assert q == "only instruction only instruction"

    def test_anchor_equals_instruction_no_duplicate_weight(self):
        q = build_rag_query_text(
            anchor_message_text="same text",
            user_text="same text",
            thread_messages=[],
            context_kind="channel_tail",
        )
        assert q == "same text same text same text"


class TestRunReactLoopRagQuery:
    @patch("common.slack.copilot_pipeline.fetch_thread_messages")
    @patch("common.slack.copilot_pipeline.slack_rag")
    @patch("common.slack.copilot_pipeline.progressive_disclosure")
    @patch("common.slack.copilot_pipeline.llm_client")
    @patch("common.slack.copilot_pipeline.slack_api")
    def test_query_channel_uses_focused_rag_text(
        self, mock_slack, mock_llm, mock_pd, mock_rag, mock_fetch,
    ):
        mock_pd.select_skills.return_value = []
        mock_pd.get_default_instruction.return_value = "default"
        mock_rag.is_ready.return_value = True
        mock_rag.query_channel.return_value = []
        mock_rag.missing_channels.return_value = []
        mock_rag.query_cross_channel.return_value = []
        mock_llm.agent_tool_loop.return_value = AgentToolLoopResult("ok", [])
        channel_tail = [{"text": "noise " * 100}]
        mock_fetch.return_value = channel_tail

        run_react_loop(
            "C",
            "T1",
            "U1",
            "modal instruction",
            thread_messages=channel_tail,
            context_kind="channel_tail",
            anchor_message_text="anchor focus",
        )

        rag_query = mock_rag.query_channel.call_args[0][1]
        assert rag_query.count("anchor focus") == 3
        assert rag_query.count("modal instruction") == 2
        assert "noise" not in rag_query


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


class TestRunReactLoopExcludedTools:
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
        mock_llm.agent_tool_loop.return_value = AgentToolLoopResult("ok", [])
        mock_fetch.return_value = [{"text": "x"}]

        run_react_loop(
            "C", "T1", "U1", "",
            excluded_tools=[SCHEDULE_PROMPT_TOOL],
        )
        tools_passed = mock_llm.agent_tool_loop.call_args[0][2]
        assert SCHEDULE_PROMPT_TOOL not in tools_passed
        assert SEND_DM_AS_APP_TOOL in tools_passed
        assert SEND_THREAD_REPLY_ON_BEHALF_OF_REQUESTER_TOOL in tools_passed
        assert SEND_THREAD_REPLY_AS_APP_TOOL in tools_passed
        assert SEND_EPHEMERAL_MESSAGE_TOOL in tools_passed
        assert LIST_USERGROUP_MEMBERS_TOOL in tools_passed
        assert LIST_USERS_TOOL in tools_passed

    @patch("common.slack.copilot_pipeline.fetch_thread_messages")
    @patch("common.slack.copilot_pipeline.slack_rag")
    @patch("common.slack.copilot_pipeline.progressive_disclosure")
    @patch("common.slack.copilot_pipeline.llm_client")
    @patch("common.slack.copilot_pipeline.slack_api")
    def test_both_thread_reply_tools_always_exposed(
        self, mock_slack, mock_llm, mock_pd, mock_rag, mock_fetch,
    ):
        mock_pd.select_skills.return_value = []
        mock_pd.get_default_instruction.return_value = "default"
        mock_rag.is_ready.return_value = True
        mock_rag.query_channel.return_value = []
        mock_rag.missing_channels.return_value = []
        mock_rag.query_cross_channel.return_value = []
        mock_llm.agent_tool_loop.return_value = AgentToolLoopResult("ok", [])
        mock_fetch.return_value = [{"text": "x"}]

        for action in (None, "send_thread_reply_on_behalf_of_requester"):
            mock_llm.agent_tool_loop.reset_mock()
            run_react_loop(
                "C",
                "T1",
                "U1",
                "",
                copilot_trigger="app_mention" if action else None,
                copilot_action=action,
            )
            tools_passed = mock_llm.agent_tool_loop.call_args[0][2]
            assert SEND_THREAD_REPLY_AS_APP_TOOL in tools_passed, action
            assert SEND_THREAD_REPLY_ON_BEHALF_OF_REQUESTER_TOOL in tools_passed, action


class TestRunReactLoopToolErrorsInOutput:
    @patch("common.slack.copilot_pipeline.fetch_thread_messages")
    @patch("common.slack.copilot_pipeline.slack_rag")
    @patch("common.slack.copilot_pipeline.progressive_disclosure")
    @patch("common.slack.copilot_pipeline.llm_client")
    @patch("common.slack.copilot_pipeline.slack_api")
    def test_appends_tool_errors_to_output_text(
        self, mock_slack, mock_llm, mock_pd, mock_rag, mock_fetch,
    ):
        mock_pd.select_skills.return_value = []
        mock_pd.get_default_instruction.return_value = "default"
        mock_rag.is_ready.return_value = True
        mock_rag.query_channel.return_value = []
        mock_rag.missing_channels.return_value = []
        mock_rag.query_cross_channel.return_value = []
        mock_llm.agent_tool_loop.return_value = AgentToolLoopResult(
            "Draft body.",
            [],
            tool_errors=[
                "send_dm_as_app: Error: requester_user_id is required to show confirmation.",
            ],
        )
        mock_fetch.return_value = [{"text": "x"}]

        out = run_react_loop("C", "T1", "U1", "hi")

        assert "Draft body." in out.text
        assert "*Tool errors*" in out.text
        assert "requester_user_id" in out.text
        assert "send_dm_as_app:" in out.text
