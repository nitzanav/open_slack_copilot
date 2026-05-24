import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from common.llm.llm_client.llm_client import AgentToolLoopResult, ToolCallRecord
from common.slack.copilot_pipeline import MESSAGE_SHORTCUT_CALLBACK_PATTERN
from common.slack.slack_bot.slack_listener_with_threads import (
    ACTION_SHORTCUT_INSTRUCTION_TEXT,
    BLOCK_SHORTCUT_INSTRUCTION,
    CALLBACK_COPILOT_SHORTCUT_DRAFT_MODAL,
)

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


def _get_registered_modal_handler(app: MagicMock, decorator):
    return decorator.registered


THREAD_3 = _load_fixture("fixture_thread_3_messages.json")


def _mock_bot_deps(mock_llm, mock_pd, mock_rag):
    mock_pd.select_skills.return_value = []
    mock_pd.get_default_instruction.return_value = "default"
    mock_pd.load_forced_skill.return_value = (
        "draft_with_copilot",
        "forced skill body",
    )
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
        "callback_id": "slack_copilot_draft_with_copilot",
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
    @patch("common.slack.slack_bot.react_runner.copilot_user_notify")
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_shortcut_opens_modal_without_llm(
        self, mock_slack_api, mock_react_notify, mock_llm, mock_pd, mock_rag, mock_fetch,
    ):
        mock_fetch.return_value = THREAD_3
        mock_llm.agent_tool_loop.return_value = AgentToolLoopResult(
            "",
            [ToolCallRecord("send_thread_reply_on_behalf_of_requester", '{"status":"tool_confirmation_requested"}')],
            [],
        )
        _mock_bot_deps(mock_llm, mock_pd, mock_rag)

        from common.slack.slack_bot.slack_listener_with_threads import register_copilot_shortcut
        from core.slack_bot import _handle_copilot

        app = MagicMock()
        shortcut_dec = _make_shortcut_decorator()
        view_dec = _make_shortcut_decorator()
        app.shortcut.return_value = shortcut_dec
        app.view.return_value = view_dec
        register_copilot_shortcut(app, _handle_copilot)
        registered_fn = _get_registered_shortcut_handler(app, shortcut_dec)
        client = MagicMock()

        shortcut = _shortcut_payload(channel_id="C1", user_id="U1")

        registered_fn(ack=MagicMock(), shortcut=shortcut, client=client)

        mock_fetch.assert_called_once_with("C1", "1516229200.000000")
        mock_llm.agent_tool_loop.assert_not_called()
        client.views_open.assert_called_once()
        mock_react_notify.notify_error.assert_not_called()
        mock_react_notify.notify_react_feedback.assert_not_called()

    @patch("common.slack.copilot_pipeline.fetch_thread_messages")
    @patch("common.slack.copilot_pipeline.slack_rag")
    @patch("common.slack.copilot_pipeline.progressive_disclosure")
    @patch("common.slack.copilot_pipeline.llm_client")
    @patch("common.slack.slack_bot.react_runner.copilot_user_notify")
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_shortcut_modal_submit_runs_llm_chain(
        self, mock_slack_api, mock_react_notify, mock_llm, mock_pd, mock_rag, mock_fetch,
    ):
        mock_fetch.return_value = THREAD_3
        mock_llm.agent_tool_loop.return_value = AgentToolLoopResult(
            "",
            [ToolCallRecord("send_thread_reply_on_behalf_of_requester", '{"status":"tool_confirmation_requested"}')],
            [],
        )
        _mock_bot_deps(mock_llm, mock_pd, mock_rag)

        from common.slack.slack_bot.slack_listener_with_threads import register_copilot_shortcut
        from core.slack_bot import _handle_copilot

        app = MagicMock()
        shortcut_dec = _make_shortcut_decorator()
        view_dec = _make_shortcut_decorator()
        app.shortcut.return_value = shortcut_dec
        app.view.return_value = view_dec
        register_copilot_shortcut(app, _handle_copilot)
        shortcut_fn = _get_registered_shortcut_handler(app, shortcut_dec)
        modal_fn = _get_registered_modal_handler(app, view_dec)
        client = MagicMock()

        shortcut = _shortcut_payload(channel_id="C1", user_id="U1")
        shortcut_fn(ack=MagicMock(), shortcut=shortcut, client=client)
        metadata = client.views_open.call_args[1]["view"]["private_metadata"]
        meta = json.loads(metadata)
        assert meta.get("anchor_message_text") == "Sample message"

        body = {
            "view": {
                "private_metadata": metadata,
                "state": {
                    "values": {
                        BLOCK_SHORTCUT_INSTRUCTION: {
                            ACTION_SHORTCUT_INSTRUCTION_TEXT: {
                                "value": "Draft reply on my behalf for this thread",
                            },
                        },
                    },
                },
            },
        }
        modal_fn(ack=MagicMock(), body=body, _client=MagicMock())

        assert mock_fetch.call_count == 2
        mock_llm.agent_tool_loop.assert_called_once()
        prompt = mock_llm.agent_tool_loop.call_args[0][0]
        for msg in THREAD_3:
            assert msg["text"] in prompt

        rag_query = mock_rag.query_channel.call_args[0][1]
        assert rag_query.count("Sample message") == 3
        assert rag_query.count("Draft reply on my behalf for this thread") == 2

        mock_react_notify.notify_error.assert_not_called()
        mock_react_notify.notify_react_feedback.assert_not_called()

    @patch("common.slack.copilot_pipeline.fetch_channel_tail_messages")
    @patch("common.slack.copilot_pipeline.slack_rag")
    @patch("common.slack.copilot_pipeline.progressive_disclosure")
    @patch("common.slack.copilot_pipeline.llm_client")
    @patch("common.slack.slack_bot.react_runner.copilot_user_notify")
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_shortcut_opens_modal_channel_root(
        self, mock_slack_api, mock_react_notify, mock_llm, mock_pd, mock_rag, mock_tail,
    ):
        mock_tail.return_value = THREAD_3
        mock_llm.agent_tool_loop.return_value = AgentToolLoopResult(
            "",
            [ToolCallRecord("send_thread_reply_on_behalf_of_requester", '{"status":"tool_confirmation_requested"}')],
            [],
        )
        _mock_bot_deps(mock_llm, mock_pd, mock_rag)

        from common.slack.slack_bot.slack_listener_with_threads import register_copilot_shortcut
        from core.slack_bot import _handle_copilot

        app = MagicMock()
        shortcut_dec = _make_shortcut_decorator()
        view_dec = _make_shortcut_decorator()
        app.shortcut.return_value = shortcut_dec
        app.view.return_value = view_dec
        register_copilot_shortcut(app, _handle_copilot)
        registered_fn = _get_registered_shortcut_handler(app, shortcut_dec)
        client = MagicMock()

        shortcut = _shortcut_payload(thread_ts=None)

        registered_fn(ack=MagicMock(), shortcut=shortcut, client=client)

        mock_tail.assert_called_once_with("C1")
        mock_llm.agent_tool_loop.assert_not_called()
        client.views_open.assert_called_once()

        mock_react_notify.notify_error.assert_not_called()
        mock_react_notify.notify_react_feedback.assert_not_called()

    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_shortcut_callback_registration(self, mock_slack_api):
        from common.slack.slack_bot.slack_listener_with_threads import register_copilot_shortcut

        app = MagicMock()
        register_copilot_shortcut(app, MagicMock())
        assert app.shortcut.call_count == 1
        pat = app.shortcut.call_args[0][0]
        assert pat is MESSAGE_SHORTCUT_CALLBACK_PATTERN
        app.view.assert_called_once_with(CALLBACK_COPILOT_SHORTCUT_DRAFT_MODAL)
