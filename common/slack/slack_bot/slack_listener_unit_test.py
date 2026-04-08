from unittest.mock import patch, MagicMock

from common.slack.slack_bot.slack_listener_with_threads import (
    register_copilot_app_mention,
    register_copilot_command,
    register_copilot_shortcut,
    _extract_thread_ts,
)


def _get_registered_handler(app: MagicMock):
    """Extract the function passed to @app.command("/copilot") decorator."""
    return app.command.return_value.call_args[0][0]


def _get_registered_shortcut_handler(app: MagicMock):
    """Extract the function passed to @app.shortcut() decorator."""
    return app.shortcut.return_value.call_args[0][0]


def _get_registered_app_mention_handler(app: MagicMock):
    return app.event.return_value.call_args[0][0]


class TestExtractThreadTs:
    def test_from_thread_ts(self):
        assert _extract_thread_ts({"thread_ts": "123.456"}) == "123.456"

    def test_from_message_ts_fallback(self):
        assert _extract_thread_ts({"message_ts": "789.012"}) == "789.012"

    def test_thread_ts_takes_priority(self):
        assert _extract_thread_ts({"thread_ts": "111", "message_ts": "222"}) == "111"

    def test_none_when_missing(self):
        assert _extract_thread_ts({}) is None


class TestRegisterCopilotCommand:
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_registers_slash_command(self, mock_slack_api):
        app = MagicMock()
        register_copilot_command(app, MagicMock())
        app.command.assert_called_once_with("/copilot")

    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_handler_called_with_thread_data(self, mock_slack_api):
        app = MagicMock()
        handler = MagicMock()

        register_copilot_command(app, handler)
        registered_fn = _get_registered_handler(app)

        registered_fn(ack=MagicMock(), command={
            "channel_id": "C1", "user_id": "U1", "text": "help me", "thread_ts": "T1"
        })

        handler.assert_called_once_with(
            channel_id="C1", thread_ts="T1", user_id="U1",
            user_text="help me", channel_name=None, context_kind="thread",
            copilot_trigger="slash_command",
            copilot_action="send_thread_reply",
        )

    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_no_thread_ts_sends_error(self, mock_slack_api):
        app = MagicMock()
        handler = MagicMock()

        register_copilot_command(app, handler)
        registered_fn = _get_registered_handler(app)

        registered_fn(ack=MagicMock(), command={"channel_id": "C1", "user_id": "U1", "text": ""})

        handler.assert_not_called()
        mock_slack_api.send_ephemeral.assert_called_once()
        assert "thread" in mock_slack_api.send_ephemeral.call_args[0][3].lower()

class TestRegisterCopilotShortcut:
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_registers_message_shortcut(self, mock_slack_api):
        app = MagicMock()
        register_copilot_shortcut(app, MagicMock())
        app.shortcut.assert_called_once_with("draft_with_copilot")

    @patch("common.slack.slack_bot.slack_listener_with_threads.resolve_copilot_slack_context")
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_shortcut_handler_called_with_thread_data(self, mock_slack_api, mock_resolve):
        app = MagicMock()
        handler = MagicMock()
        msgs = [{"user": "U1", "text": "hello"}]
        mock_resolve.return_value = ("1516229200.000000", msgs)

        register_copilot_shortcut(app, handler)
        registered_fn = _get_registered_shortcut_handler(app)

        shortcut = {
            "channel": {"id": "C1", "name": "team-chat"},
            "user": {"id": "U1"},
            "message": {"ts": "1516229207.000133", "thread_ts": "1516229200.000000"},
        }
        registered_fn(ack=MagicMock(), shortcut=shortcut, client=MagicMock())

        mock_resolve.assert_called_once_with("C1", shortcut["message"])
        handler.assert_called_once_with(
            channel_id="C1", thread_ts="1516229200.000000", user_id="U1",
            user_text="", thread_messages=msgs, channel_name="team-chat",
            context_kind="thread",
            copilot_trigger="message_shortcut",
            copilot_action="send_thread_reply",
        )

    @patch("common.slack.slack_bot.slack_listener_with_threads.resolve_copilot_slack_context")
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_shortcut_in_channel_message_uses_message_ts_as_thread(self, mock_slack_api, mock_resolve):
        app = MagicMock()
        handler = MagicMock()
        msgs = [{"user": "U2", "text": "root msg"}]
        mock_resolve.return_value = ("1516229207.000133", msgs)

        register_copilot_shortcut(app, handler)
        registered_fn = _get_registered_shortcut_handler(app)

        shortcut = {
            "channel": {"id": "C2"},
            "user": {"id": "U1"},
            "message": {"ts": "1516229207.000133"},
        }
        registered_fn(ack=MagicMock(), shortcut=shortcut, client=MagicMock())

        mock_resolve.assert_called_once_with("C2", shortcut["message"])
        handler.assert_called_once_with(
            channel_id="C2", thread_ts="1516229207.000133", user_id="U1",
            user_text="", thread_messages=msgs, channel_name=None,
            context_kind="channel_tail",
            copilot_trigger="message_shortcut",
            copilot_action="send_thread_reply",
        )


class TestRegisterCopilotAppMention:
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_registers_app_mention_event(self, mock_slack_api):
        app = MagicMock()
        register_copilot_app_mention(app, MagicMock(), bot_user_id="UBOT")
        app.event.assert_called_once_with("app_mention")

    @patch("common.slack.slack_bot.slack_listener_with_threads.resolve_copilot_slack_context")
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_mention_root_uses_resolve_and_handler(self, mock_slack_api, mock_resolve):
        app = MagicMock()
        handler = MagicMock()
        msgs = [{"text": "older"}, {"text": "newer"}]
        mock_resolve.return_value = ("111.222", msgs)

        register_copilot_app_mention(app, handler, bot_user_id="UBOT")
        registered_fn = _get_registered_app_mention_handler(app)

        event = {
            "type": "app_mention",
            "channel": "C9",
            "user": "UHUMAN",
            "text": "<@UBOT> make it brief",
            "ts": "111.222",
        }
        registered_fn(event=event)

        mock_resolve.assert_called_once_with("C9", {"ts": "111.222"})
        handler.assert_called_once_with(
            channel_id="C9",
            thread_ts="111.222",
            user_id="UHUMAN",
            user_text="make it brief",
            thread_messages=msgs,
            channel_name=None,
            context_kind="channel_tail",
            copilot_trigger="app_mention",
            copilot_action="send_thread_reply",
        )

    @patch("common.slack.slack_bot.slack_listener_with_threads.resolve_copilot_slack_context")
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_mention_in_thread_passes_thread_ts(self, mock_slack_api, mock_resolve):
        app = MagicMock()
        handler = MagicMock()
        msgs = [{"text": "in thread"}]
        mock_resolve.return_value = ("100.000", msgs)

        register_copilot_app_mention(app, handler, bot_user_id="UBOT")
        registered_fn = _get_registered_app_mention_handler(app)

        event = {
            "type": "app_mention",
            "channel": "C9",
            "user": "UHUMAN",
            "text": "<@UBOT>",
            "ts": "101.000",
            "thread_ts": "100.000",
        }
        registered_fn(event=event)

        mock_resolve.assert_called_once_with(
            "C9", {"ts": "101.000", "thread_ts": "100.000"},
        )
        handler.assert_called_once_with(
            channel_id="C9",
            thread_ts="100.000",
            user_id="UHUMAN",
            user_text="",
            thread_messages=msgs,
            channel_name=None,
            context_kind="thread",
            copilot_trigger="app_mention",
            copilot_action="send_thread_reply",
        )

    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_mention_skips_subtype(self, mock_slack_api):
        app = MagicMock()
        handler = MagicMock()
        register_copilot_app_mention(app, handler, bot_user_id="UBOT")
        registered_fn = _get_registered_app_mention_handler(app)

        registered_fn(event={
            "type": "app_mention",
            "subtype": "bot_message",
            "channel": "C9",
            "user": "UBOT",
            "text": "<@UBOT>",
            "ts": "1.0",
        })
        handler.assert_not_called()

    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_mention_skips_own_bot_user(self, mock_slack_api):
        app = MagicMock()
        handler = MagicMock()
        register_copilot_app_mention(app, handler, bot_user_id="UBOT")
        registered_fn = _get_registered_app_mention_handler(app)

        registered_fn(event={
            "type": "app_mention",
            "channel": "C9",
            "user": "UBOT",
            "text": "<@UBOT> hi",
            "ts": "1.0",
        })
        handler.assert_not_called()

    @patch("common.slack.slack_bot.slack_listener_with_threads.resolve_copilot_slack_context")
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_mention_resolve_error_sends_ephemeral(self, mock_slack_api, mock_resolve):
        from common.slack.copilot_pipeline import ThreadFetchError

        mock_resolve.side_effect = ThreadFetchError("nope")
        app = MagicMock()
        register_copilot_app_mention(app, MagicMock(), bot_user_id="UBOT")
        registered_fn = _get_registered_app_mention_handler(app)

        registered_fn(event={
            "type": "app_mention",
            "channel": "C9",
            "user": "UHUMAN",
            "text": "<@UBOT>",
            "ts": "7.0",
            "thread_ts": "6.0",
        })

        mock_slack_api.send_ephemeral.assert_called_once_with(
            "C9", "6.0", "UHUMAN",
            "Add me to this channel first. /invite @CoPilot",
        )
