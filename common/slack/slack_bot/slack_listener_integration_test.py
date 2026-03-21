import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

FIXTURES = Path(__file__).parent.parent.parent.parent / "tests" / "fixtures"


def _load_fixture(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text())


def _get_registered_handler(app: MagicMock):
    return app.command.return_value.call_args[0][0]


THREAD_3 = _load_fixture("fixture_thread_3_messages.json")
THREAD_1 = _load_fixture("fixture_thread_singleton.json")


def _mock_bot_deps(mock_llm, mock_pd, mock_rag):
    mock_pd.select_skills.return_value = []
    mock_pd.get_default_instruction.return_value = "default"
    mock_rag.is_ready.return_value = True
    mock_rag.query_channel.return_value = []
    mock_rag.missing_channels.return_value = []
    mock_rag.query_cross_channel.return_value = []


class TestSlashCommandEndToEnd:

    @patch("common.slack.copilot_pipeline.fetch_thread_messages")
    @patch("common.slack.copilot_pipeline.slack_rag")
    @patch("common.slack.copilot_pipeline.progressive_disclosure")
    @patch("common.slack.copilot_pipeline.llm_client")
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_full_chain(self, mock_slack_api, mock_llm, mock_pd, mock_rag, mock_fetch):
        mock_fetch.return_value = THREAD_3
        mock_llm.agent_tool_loop.return_value = "Generated draft reply"
        _mock_bot_deps(mock_llm, mock_pd, mock_rag)

        from common.slack.slack_bot.slack_listener_with_threads import register_copilot_command
        from core.slack_bot import _handle_copilot

        app = MagicMock()
        register_copilot_command(app, _handle_copilot)
        registered_fn = _get_registered_handler(app)

        command = {"channel_id": "C1", "user_id": "U1", "text": "reply politely", "thread_ts": "T1"}

        with patch("core.slack_bot.slack_api") as mock_core_slack:
            registered_fn(ack=MagicMock(), command=command)

            mock_llm.agent_tool_loop.assert_called_once()
            prompt = mock_llm.agent_tool_loop.call_args[0][0]
            assert "reply politely" in prompt
            for msg in THREAD_3:
                assert msg["text"] in prompt

            mock_core_slack.send_ephemeral.assert_called_once_with(
                "C1", "T1", "U1", "Generated draft reply"
            )

    @patch("common.slack.copilot_pipeline.fetch_thread_messages")
    @patch("common.slack.copilot_pipeline.slack_rag")
    @patch("common.slack.copilot_pipeline.progressive_disclosure")
    @patch("common.slack.copilot_pipeline.llm_client")
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_singleton_thread_end_to_end(self, mock_slack_api, mock_llm, mock_pd, mock_rag, mock_fetch):
        mock_fetch.return_value = THREAD_1
        mock_llm.agent_tool_loop.return_value = "Singleton draft"
        _mock_bot_deps(mock_llm, mock_pd, mock_rag)

        from common.slack.slack_bot.slack_listener_with_threads import register_copilot_command
        from core.slack_bot import _handle_copilot

        app = MagicMock()
        register_copilot_command(app, _handle_copilot)
        registered_fn = _get_registered_handler(app)

        command = {"channel_id": "C2", "user_id": "U2", "text": "", "thread_ts": "T2"}

        with patch("core.slack_bot.slack_api") as mock_core_slack:
            registered_fn(ack=MagicMock(), command=command)
            mock_core_slack.send_ephemeral.assert_called_once_with("C2", "T2", "U2", "Singleton draft")

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
        )

    def test_callback_registration(self):
        from common.slack.slack_bot.slack_listener_with_threads import register_copilot_command

        app = MagicMock()
        register_copilot_command(app, MagicMock())
        app.command.assert_called_with("/copilot")
