from unittest.mock import patch

import pytest

from common.conversations.conversations import Conversation
from common.llm.llm_client.llm_client import AgentToolLoopResult, ToolCallRecord
from common.skill_runs import skill_runs
from common.slack.copilot_pipeline import (
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


def _main_step(instruction: str) -> dict[str, str]:
    return {"main": instruction}


@pytest.fixture(autouse=True)
def _isolated_data_layer(tmp_path):
    from config.config import settings

    settings.set("data_layer.root", str(tmp_path))
    yield


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
    @patch("common.slack.copilot_pipeline.run_conversation_driver")
    @patch("common.slack.copilot_pipeline.fetch_thread_messages")
    @patch("common.slack.copilot_pipeline.slack_rag")
    @patch("common.slack.copilot_pipeline.select_skill")
    @patch("common.slack.copilot_pipeline.slack_api")
    def test_excluded_tools_omit_schedule_keep_others(
        self, mock_slack, mock_select_skill, mock_rag, mock_fetch, mock_driver,
    ):
        mock_select_skill.return_value = ("reply/default", "default", _main_step("default"))
        mock_rag.is_ready.return_value = True
        mock_rag.query_channel.return_value = []
        mock_rag.missing_channels.return_value = []
        mock_rag.query_cross_channel.return_value = []
        mock_fetch.return_value = [{"text": "x"}]
        captured: list[list] = []

        def _fake_driver(
            conversation_id, *, tools, excluded_tools, tool_dispatch, on_agent_event,
            skip_next_step_intro,
        ):
            import common.slack.copilot_pipeline as cp

            captured.append(cp._resolve_tools(tools, excluded_tools))
            return AgentToolLoopResult("ok", []), {}

        mock_driver.side_effect = _fake_driver

        run_react_loop(
            "C", "T1", "U1", "",
            excluded_tools=[SCHEDULE_PROMPT_TOOL],
        )
        tools_passed = captured[0]
        assert SCHEDULE_PROMPT_TOOL not in tools_passed
        assert SEND_DM_AS_APP_TOOL in tools_passed
        assert SEND_THREAD_REPLY_ON_BEHALF_OF_REQUESTER_TOOL in tools_passed
        assert SEND_THREAD_REPLY_AS_APP_TOOL in tools_passed
        assert SEND_EPHEMERAL_MESSAGE_TOOL in tools_passed
        assert LIST_USERGROUP_MEMBERS_TOOL in tools_passed
        assert LIST_USERS_TOOL in tools_passed

    @patch("common.slack.copilot_pipeline.run_conversation_driver")
    @patch("common.slack.copilot_pipeline.fetch_thread_messages")
    @patch("common.slack.copilot_pipeline.slack_rag")
    @patch("common.slack.copilot_pipeline.select_skill")
    @patch("common.slack.copilot_pipeline.slack_api")
    def test_both_thread_reply_tools_always_exposed(
        self, mock_slack, mock_select_skill, mock_rag, mock_fetch, mock_driver,
    ):
        mock_select_skill.return_value = ("reply/default", "default", _main_step("default"))
        mock_rag.is_ready.return_value = True
        mock_rag.query_channel.return_value = []
        mock_rag.missing_channels.return_value = []
        mock_rag.query_cross_channel.return_value = []
        mock_fetch.return_value = [{"text": "x"}]
        captured: list[list] = []

        def _fake_driver(
            conversation_id, *, tools, excluded_tools, tool_dispatch, on_agent_event,
            skip_next_step_intro,
        ):
            import common.slack.copilot_pipeline as cp

            captured.append(cp._resolve_tools(tools, excluded_tools))
            return AgentToolLoopResult("ok", []), {}

        mock_driver.side_effect = _fake_driver

        for action in (None, "send_thread_reply_on_behalf_of_requester"):
            captured.clear()
            run_react_loop(
                "C",
                "T1",
                "U1",
                "",
                copilot_trigger="app_mention" if action else None,
                copilot_action=action,
            )
            tools_passed = captured[0]
            assert SEND_THREAD_REPLY_AS_APP_TOOL in tools_passed, action
            assert SEND_THREAD_REPLY_ON_BEHALF_OF_REQUESTER_TOOL in tools_passed, action


class TestRunReactLoopToolErrorsInOutput:
    @patch("common.slack.copilot_pipeline.run_conversation_driver")
    @patch("common.slack.copilot_pipeline.fetch_thread_messages")
    @patch("common.slack.copilot_pipeline.slack_rag")
    @patch("common.slack.copilot_pipeline.select_skill")
    @patch("common.slack.copilot_pipeline.slack_api")
    def test_appends_tool_errors_to_output_text(
        self, mock_slack, mock_select_skill, mock_rag, mock_fetch, mock_driver,
    ):
        mock_select_skill.return_value = ("reply/default", "default", _main_step("default"))
        mock_rag.is_ready.return_value = True
        mock_rag.query_channel.return_value = []
        mock_rag.missing_channels.return_value = []
        mock_rag.query_cross_channel.return_value = []
        mock_driver.return_value = (
            AgentToolLoopResult(
                "Draft body.",
                [],
                tool_errors=[
                    "send_dm_as_app: Error: requester_user_id is required to show confirmation.",
                ],
            ),
            Conversation(),
        )
        mock_fetch.return_value = [{"text": "x"}]

        out = run_react_loop("C", "T1", "U1", "hi")

        assert "Draft body." in out.text
        assert "*Tool errors*" in out.text
        assert "requester_user_id" in out.text
        assert "send_dm_as_app:" in out.text


class TestRunReactLoopEnrichesSkillRunsRow:
    @patch("common.slack.copilot_pipeline.run_conversation_driver")
    @patch("common.slack.copilot_pipeline.fetch_thread_messages")
    @patch("common.slack.copilot_pipeline.slack_rag")
    @patch("common.slack.copilot_pipeline.select_skill")
    @patch("common.slack.copilot_pipeline.slack_api")
    def test_enriches_existing_row_with_run_log(
        self, mock_slack, mock_select_skill, mock_rag, mock_fetch, mock_driver,
    ):
        mock_select_skill.return_value = ("reply/x", "x", _main_step("x"))
        mock_rag.is_ready.return_value = True
        mock_rag.query_channel.return_value = []
        mock_rag.missing_channels.return_value = []
        mock_rag.query_cross_channel.return_value = []
        mock_fetch.return_value = [{"user": "U1", "text": "msg"}]

        captured_action_ts: list[str] = []

        def fake_driver(
            conversation_id, *, tools, excluded_tools, tool_dispatch, on_agent_event,
            skip_next_step_intro,
        ):
            from common.tools.react_context import get_invocation

            inv = get_invocation() or {}
            captured_action_ts.append(str(inv.get("action_ts") or ""))
            ts = inv.get("thread_ts") or ""
            at = inv.get("action_ts") or ""
            sid = inv.get("skill_id")
            skill_runs.init_run(
                skill_id=sid,
                channel_id=inv["channel_id"],
                thread_ts=ts,
                action_ts=at,
                requester_user_id=inv["user_id"],
                tool_name="send_dm_as_app",
                payload={"target_user_id": "U2"},
                text="draft body",
                conversation_id=inv.get("conversation_id"),
            )
            return AgentToolLoopResult(
                "ok",
                [ToolCallRecord("send_dm_as_app", '{"status":"tool_confirmation_requested"}')],
                [],
                waiting_for_confirmation=True,
            ), {}

        mock_driver.side_effect = fake_driver

        run_react_loop("C", "T1", "U_PREP", "hi")

        key = skill_runs._row_key("T1", captured_action_ts[0])
        row = skill_runs.get(key)
        assert row is not None
        assert row["run_log"]["final_text"]
        names = [t["name"] for t in row["run_log"]["tool_trace"]]
        assert "send_dm_as_app" in names
