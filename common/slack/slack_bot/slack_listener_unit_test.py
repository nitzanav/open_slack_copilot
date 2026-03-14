from unittest.mock import patch, MagicMock

from common.slack.slack_bot.slack_listener_with_threads import register_copilot_command, _extract_thread_ts


def _get_registered_handler(app: MagicMock):
    """Extract the function passed to @app.command("/copilot") decorator."""
    return app.command.return_value.call_args[0][0]


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
        mock_slack_api.read_thread.return_value = [{"user": "U1", "text": "hello"}]

        register_copilot_command(app, handler)
        registered_fn = _get_registered_handler(app)

        registered_fn(ack=MagicMock(), command={
            "channel_id": "C1", "user_id": "U1", "text": "help me", "thread_ts": "T1"
        })

        handler.assert_called_once_with(
            channel_id="C1", thread_ts="T1", user_id="U1",
            user_text="help me", thread_messages=[{"user": "U1", "text": "hello"}]
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

    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_read_thread_error_sends_channel_error(self, mock_slack_api):
        app = MagicMock()
        handler = MagicMock()
        mock_slack_api.read_thread.side_effect = Exception("not_in_channel")

        register_copilot_command(app, handler)
        registered_fn = _get_registered_handler(app)

        registered_fn(ack=MagicMock(), command={
            "channel_id": "C1", "user_id": "U1", "text": "", "thread_ts": "T1"
        })

        handler.assert_not_called()
        assert "channel" in mock_slack_api.send_ephemeral.call_args[0][3].lower()
