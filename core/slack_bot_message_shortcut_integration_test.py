import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from common.llm.llm_client.llm_client import AgentToolLoopResult, ToolCallRecord

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"


def _load_fixture(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text())


def _make_shortcut_decorator():
    def decorator(fn):
        decorator.registered = fn
        return fn
    return decorator


def _get_registered_shortcut_handler(app: MagicMock, decorator):
    return decorator.registered


THREAD_3 = _load_fixture("fixture_thread_3_messages.json")


def _mock_bot_deps(mock_llm, mock_pd, mock_rag):
    mock_pd.select_skills.return_value = []
    mock_pd.get_default_instruction.return_value = "default"
    mock_rag.is_ready.return_value = True
    mock_rag.query_channel.return_value = []
    mock_rag.missing_channels.return_value = []
    mock_rag.query_cross_channel.return_value = []


def _shortcut_payload(channel_id: str = "C1", user_id: str = "U1",
                      message_ts: str = "1516229207.000133",
                      thread_ts: str | None = "1516229200.000000") -> dict:
    message = {"ts": message_ts, "type": "message", "text": "Sample message"}
    if thread_ts:
        message["thread_ts"] = thread_ts
    return {
        "type": "message_action",
        "callback_id": "draft_with_copilot",
        "channel": {"id": channel_id, "name": "general"},
        "user": {"id": user_id, "name": "alice"},
        "message": message,
        "response_url": "https://hooks.slack.com/actions/T0/0/xxx",
        "trigger_id": "13345224609.8534564800.abc123",
    }


class TestMessageShortcutEndToEnd:

    @patch("common.slack.copilot_pipeline.fetch_thread_messages")
    @patch("common.slack.copilot_pipeline.slack_rag")
    @patch("common.slack.copilot_pipeline.progressive_disclosure")
    @patch("common.slack.copilot_pipeline.llm_client")
    @patch("common.slack.slack_bot.react_runner.slack_api")
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_shortcut_full_chain_sends_reply(
        self, mock_slack_api, mock_react_slack, mock_llm, mock_pd, mock_rag, mock_fetch,
    ):
        mock_fetch.return_value = THREAD_3
        mock_llm.agent_tool_loop.return_value = AgentToolLoopResult(
            "",
            [ToolCallRecord("send_thread_reply", '{"status":"tool_confirmation_requested"}')],
            [],
        )
        _mock_bot_deps(mock_llm, mock_pd, mock_rag)

        from common.slack.slack_bot.slack_listener_with_threads import register_copilot_shortcut
        from core.slack_bot import _handle_copilot

        app = MagicMock()
        decorator = _make_shortcut_decorator()
        app.shortcut.return_value = decorator
        register_copilot_shortcut(app, _handle_copilot)
        registered_fn = _get_registered_shortcut_handler(app, decorator)

        shortcut = _shortcut_payload(channel_id="C1", user_id="U1")

        registered_fn(ack=MagicMock(), shortcut=shortcut, client=MagicMock())

        mock_fetch.assert_called_once_with("C1", "1516229200.000000")
        mock_llm.agent_tool_loop.assert_called_once()
        prompt = mock_llm.agent_tool_loop.call_args[0][0]
        for msg in THREAD_3:
            assert msg["text"] in prompt

        mock_react_slack.send_ephemeral.assert_not_called()

    @patch("common.slack.copilot_pipeline.fetch_channel_tail_messages")
    @patch("common.slack.copilot_pipeline.slack_rag")
    @patch("common.slack.copilot_pipeline.progressive_disclosure")
    @patch("common.slack.copilot_pipeline.llm_client")
    @patch("common.slack.slack_bot.react_runner.slack_api")
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_shortcut_channel_message_uses_message_ts(
        self, mock_slack_api, mock_react_slack, mock_llm, mock_pd, mock_rag, mock_tail,
    ):
        mock_tail.return_value = THREAD_3
        mock_llm.agent_tool_loop.return_value = AgentToolLoopResult(
            "",
            [ToolCallRecord("send_thread_reply", '{"status":"tool_confirmation_requested"}')],
            [],
        )
        _mock_bot_deps(mock_llm, mock_pd, mock_rag)

        from common.slack.slack_bot.slack_listener_with_threads import register_copilot_shortcut
        from core.slack_bot import _handle_copilot

        app = MagicMock()
        decorator = _make_shortcut_decorator()
        app.shortcut.return_value = decorator
        register_copilot_shortcut(app, _handle_copilot)
        registered_fn = _get_registered_shortcut_handler(app, decorator)

        shortcut = _shortcut_payload(thread_ts=None)

        registered_fn(ack=MagicMock(), shortcut=shortcut, client=MagicMock())

        mock_tail.assert_called_once_with("C1")
        mock_react_slack.send_ephemeral.assert_not_called()

    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_shortcut_callback_registration(self, mock_slack_api):
        from common.slack.slack_bot.slack_listener_with_threads import register_copilot_shortcut

        app = MagicMock()
        register_copilot_shortcut(app, MagicMock())
        app.shortcut.assert_called_with("draft_with_copilot")
