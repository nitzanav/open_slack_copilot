import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from common.conversations.conversations import Conversation
from common.llm.llm_client.llm_client import AgentToolLoopResult, ToolCallRecord


def _waiting_conversation() -> Conversation:
    return Conversation(is_waiting_for_confirmation=True)

FIXTURES = Path(__file__).parent.parent.parent.parent / "tests" / "fixtures"


def _load_fixture(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text())


def _get_registered_handler(app: MagicMock):
    return app.command.return_value.call_args[0][0]


THREAD_3 = _load_fixture("fixture_thread_3_messages.json")
THREAD_1 = _load_fixture("fixture_thread_singleton.json")

_DEFAULT_TRIPLE = (
    "reply/default",
    "default",
    {"main": "default"},
)


@pytest.fixture(autouse=True)
def _isolated_data_layer(tmp_path):
    from config.config import settings

    settings.set("data_layer.root", str(tmp_path))
    yield


def _mock_bot_deps(mock_pd, mock_rag):
    mock_pd.select_single_skill.return_value = _DEFAULT_TRIPLE
    mock_rag.is_ready.return_value = True
    mock_rag.query_channel.return_value = []
    mock_rag.missing_channels.return_value = []
    mock_rag.query_cross_channel.return_value = []


class TestSlashCommandEndToEnd:

    @patch("common.slack.slack_bot.react_runner.fetch_thread_messages")
    @patch("common.slack.copilot_pipeline.slack_rag")
    @patch("common.slack.copilot_pipeline.progressive_disclosure")
    @patch("common.slack.copilot_pipeline.run_conversation_driver")
    @patch("common.slack.slack_bot.react_runner.copilot_user_notify")
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_full_chain(self, mock_slack_api, mock_react_notify, mock_driver, mock_pd, mock_rag, mock_fetch):
        mock_fetch.return_value = THREAD_3
        mock_driver.return_value = (
            AgentToolLoopResult(
                "",
                [
                    ToolCallRecord(
                        "send_thread_reply_on_behalf_of_requester",
                        '{"status":"tool_confirmation_requested","detail":"ok"}',
                    ),
                ],
                [],
                waiting_for_confirmation=True,
            ),
            _waiting_conversation(),
        )
        _mock_bot_deps(mock_pd, mock_rag)

        from common.conversations import conversations
        from common.slack.slack_bot.slack_listener_with_threads import register_copilot_command
        from core.slack_bot import _handle_copilot

        app = MagicMock()
        register_copilot_command(app, _handle_copilot)
        registered_fn = _get_registered_handler(app)

        command = {"channel_id": "C1", "user_id": "U1", "text": "reply politely", "thread_ts": "T1"}

        registered_fn(ack=MagicMock(), command=command)

        mock_driver.assert_called_once()
        cid = mock_driver.call_args[0][0]
        conv = conversations.get(cid)
        assert conv is not None
        sys0 = str(conv.messages[0].get("content") or "")
        assert "reply politely" in sys0
        for msg in THREAD_3:
            assert msg["text"] in sys0

        mock_react_notify.notify_error.assert_not_called()
        mock_react_notify.notify_react_feedback.assert_not_called()

    @patch("common.slack.slack_bot.react_runner.fetch_thread_messages")
    @patch("common.slack.copilot_pipeline.slack_rag")
    @patch("common.slack.copilot_pipeline.progressive_disclosure")
    @patch("common.slack.copilot_pipeline.run_conversation_driver")
    @patch("common.slack.slack_bot.react_runner.copilot_user_notify")
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_singleton_thread_end_to_end(self, mock_slack_api, mock_react_notify, mock_driver, mock_pd, mock_rag, mock_fetch):
        mock_fetch.return_value = THREAD_1
        mock_driver.return_value = (
            AgentToolLoopResult(
                "",
                [ToolCallRecord("send_thread_reply_on_behalf_of_requester", '{"status":"tool_confirmation_requested"}')],
                [],
                waiting_for_confirmation=True,
            ),
            _waiting_conversation(),
        )
        _mock_bot_deps(mock_pd, mock_rag)

        from common.slack.slack_bot.slack_listener_with_threads import register_copilot_command
        from core.slack_bot import _handle_copilot

        app = MagicMock()
        register_copilot_command(app, _handle_copilot)
        registered_fn = _get_registered_handler(app)

        command = {"channel_id": "C2", "user_id": "U2", "text": "", "thread_ts": "T2"}

        registered_fn(ack=MagicMock(), command=command)
        mock_react_notify.notify_error.assert_not_called()
        mock_react_notify.notify_react_feedback.assert_not_called()

    def test_thread_enrichment_passes_correct_ts(self):
        from common.slack.slack_bot.slack_listener_with_threads import register_copilot_command

        app = MagicMock()
        handler = MagicMock()
        register_copilot_command(app, handler)
        registered_fn = _get_registered_handler(app)

        command = {"channel_id": "C1", "user_id": "U1", "text": "", "thread_ts": "EXACT_TS_123"}
        registered_fn(ack=MagicMock(), command=command)

        handler.assert_called_once_with(
            channel_id="C1",
            thread_ts="EXACT_TS_123",
            user_id="U1",
            user_text="",
            channel_name=None,
            context_kind="thread",
            copilot_trigger="slash_command",
            copilot_action="send_thread_reply_on_behalf_of_requester",
        )

    def test_callback_registration(self):
        from common.slack.slack_bot.slack_listener_with_threads import register_copilot_command

        app = MagicMock()
        register_copilot_command(app, MagicMock())
        app.command.assert_called_with("/copilot")
