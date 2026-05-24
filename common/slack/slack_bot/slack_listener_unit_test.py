import json
from unittest.mock import patch, MagicMock

from common.slack.copilot_pipeline import MESSAGE_SHORTCUT_CALLBACK_PATTERN
from common.slack.slack_bot.slack_listener_with_threads import (
    ACTION_SHORTCUT_INSTRUCTION_TEXT,
    BLOCK_SHORTCUT_INSTRUCTION,
    CALLBACK_COPILOT_SHORTCUT_DRAFT_MODAL,
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


def _get_registered_shortcut_modal_handler(app: MagicMock):
    """Extract the function passed to @app.view(shortcut modal) decorator."""
    return app.view.return_value.call_args[0][0]


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
            copilot_action="send_thread_reply_on_behalf_of_requester",
            anchor_message_text="help me",
        )

    @patch("common.slack.slack_bot.slack_listener_with_threads.copilot_user_notify")
    def test_no_thread_ts_sends_error(self, mock_notify):
        app = MagicMock()
        handler = MagicMock()

        register_copilot_command(app, handler)
        registered_fn = _get_registered_handler(app)

        registered_fn(ack=MagicMock(), command={"channel_id": "C1", "user_id": "U1", "text": ""})

        handler.assert_not_called()
        mock_notify.notify_error.assert_called_once()
        assert "thread" in mock_notify.notify_error.call_args[0][3].lower()

class TestRegisterCopilotShortcut:
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_registers_message_shortcut(self, mock_slack_api):
        app = MagicMock()
        register_copilot_shortcut(app, MagicMock())
        assert app.shortcut.call_count == 1
        pat = app.shortcut.call_args[0][0]
        assert pat is MESSAGE_SHORTCUT_CALLBACK_PATTERN
        app.view.assert_called_once_with(CALLBACK_COPILOT_SHORTCUT_DRAFT_MODAL)

    @patch(
        "common.slack.slack_bot.slack_listener_with_threads"
        ".skill_folder_valid_for_forced_modal",
        return_value=True,
    )
    @patch("common.slack.slack_bot.slack_listener_with_threads.load_forced_skill")
    @patch(
        "common.slack.slack_bot.slack_listener_with_threads"
        ".parse_copilot_shortcut_callback_id",
        return_value="draft_with_copilot",
    )
    @patch("common.slack.slack_bot.slack_listener_with_threads.resolve_copilot_slack_context")
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_shortcut_opens_modal_with_thread_metadata(
        self, mock_slack_api, mock_resolve, _mock_folder, mock_load_skill,
        _mock_valid,
    ):
        mock_load_skill.return_value = (
            "draft_with_copilot",
            "# Draft thread reply\n\nBody.",
        )
        app = MagicMock()
        handler = MagicMock()
        msgs = [{"user": "U1", "text": "hello"}]
        mock_resolve.return_value = ("1516229200.000000", msgs)

        register_copilot_shortcut(app, handler)
        registered_fn = _get_registered_shortcut_handler(app)
        client = MagicMock()

        shortcut = {
            "callback_id": "slack_copilot_draft_with_copilot",
            "channel": {"id": "C1", "name": "team-chat"},
            "user": {"id": "U1"},
            "message": {"ts": "1516229207.000133", "thread_ts": "1516229200.000000"},
            "trigger_id": "trigger-1",
        }
        registered_fn(ack=MagicMock(), shortcut=shortcut, client=client)

        mock_resolve.assert_called_once_with("C1", shortcut["message"])
        handler.assert_not_called()
        client.views_open.assert_called_once()
        view = client.views_open.call_args[1]["view"]
        assert view["callback_id"] == CALLBACK_COPILOT_SHORTCUT_DRAFT_MODAL
        assert view["blocks"][0]["type"] == "context"
        instr = next(
            b for b in view["blocks"] if b.get("block_id") == BLOCK_SHORTCUT_INSTRUCTION
        )
        el = instr["element"]
        assert el["initial_value"] == 'user asked to trigger skill "Draft thread reply".'
        assert "placeholder" in el
        assert instr.get("hint")
        mock_load_skill.assert_called()
        meta = json.loads(view["private_metadata"])
        assert meta == {
            "skill_folder": "draft_with_copilot",
            "channel_id": "C1",
            "message_ts": "1516229207.000133",
            "thread_ts": "1516229200.000000",
            "user_id": "U1",
            "channel_name": "team-chat",
        }

    @patch(
        "common.slack.slack_bot.slack_listener_with_threads"
        ".skill_folder_valid_for_forced_modal",
        return_value=True,
    )
    @patch("common.slack.slack_bot.slack_listener_with_threads.load_forced_skill")
    @patch(
        "common.slack.slack_bot.slack_listener_with_threads"
        ".parse_copilot_shortcut_callback_id",
        return_value="draft_with_copilot",
    )
    @patch("common.slack.slack_bot.slack_listener_with_threads.resolve_copilot_slack_context")
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_shortcut_opens_modal_for_channel_root_message(
        self, mock_slack_api, mock_resolve, _mock_folder, mock_load_skill,
        _mock_valid,
    ):
        mock_load_skill.return_value = ("draft_with_copilot", "# Draft\n")
        app = MagicMock()
        handler = MagicMock()
        msgs = [{"user": "U2", "text": "root msg"}]
        mock_resolve.return_value = ("1516229207.000133", msgs)

        register_copilot_shortcut(app, handler)
        registered_fn = _get_registered_shortcut_handler(app)
        client = MagicMock()

        shortcut = {
            "callback_id": "slack_copilot_draft_with_copilot",
            "channel": {"id": "C2"},
            "user": {"id": "U1"},
            "message": {"ts": "1516229207.000133"},
            "trigger_id": "trigger-2",
        }
        registered_fn(ack=MagicMock(), shortcut=shortcut, client=client)

        mock_resolve.assert_called_once_with("C2", shortcut["message"])
        handler.assert_not_called()
        meta = json.loads(
            client.views_open.call_args[1]["view"]["private_metadata"],
        )
        assert meta == {
            "skill_folder": "draft_with_copilot",
            "channel_id": "C2",
            "message_ts": "1516229207.000133",
            "user_id": "U1",
        }
        assert "thread_ts" not in meta

    @patch(
        "common.slack.slack_bot.slack_listener_with_threads"
        ".skill_folder_valid_for_forced_modal",
        return_value=True,
    )
    @patch(
        "common.slack.slack_bot.slack_listener_with_threads"
        ".parse_copilot_shortcut_callback_id",
        return_value="draft_with_copilot",
    )
    @patch("common.slack.slack_bot.slack_listener_with_threads.resolve_copilot_slack_context")
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_shortcut_resolve_error_does_not_open_modal(
        self, mock_slack_api, mock_resolve, _mock_folder, _mock_valid,
    ):
        from common.slack.copilot_pipeline import ThreadFetchError

        mock_resolve.side_effect = ThreadFetchError("nope")
        app = MagicMock()
        handler = MagicMock()
        register_copilot_shortcut(app, handler)
        registered_fn = _get_registered_shortcut_handler(app)
        client = MagicMock()
        shortcut = {
            "callback_id": "slack_copilot_draft_with_copilot",
            "channel": {"id": "C1", "name": "x"},
            "user": {"id": "U1"},
            "message": {"ts": "1.0", "thread_ts": "0.9"},
            "trigger_id": "t",
        }
        registered_fn(ack=MagicMock(), shortcut=shortcut, client=client)
        handler.assert_not_called()
        client.views_open.assert_not_called()

    @patch(
        "common.slack.slack_bot.slack_listener_with_threads"
        ".skill_folder_valid_for_forced_modal",
        return_value=False,
    )
    @patch(
        "common.slack.slack_bot.slack_listener_with_threads"
        ".parse_copilot_shortcut_callback_id",
        return_value="summarize_thread",
    )
    @patch("common.slack.slack_bot.slack_listener_with_threads.resolve_copilot_slack_context")
    @patch("common.slack.slack_bot.slack_listener_with_threads.copilot_user_notify")
    def test_shortcut_missing_skill_sends_ephemeral_error(
        self, mock_notify, mock_resolve, _mock_parse, _mock_valid,
    ):
        app = MagicMock()
        handler = MagicMock()
        register_copilot_shortcut(app, handler)
        registered_fn = _get_registered_shortcut_handler(app)
        client = MagicMock()

        shortcut = {
            "callback_id": "slack_copilot_summarize_thread",
            "channel": {"id": "C1", "name": "x"},
            "user": {"id": "U1"},
            "message": {"ts": "1.0", "thread_ts": "0.9"},
            "trigger_id": "t",
            "response_url": "https://hooks.slack.com/...",
        }
        registered_fn(ack=MagicMock(), shortcut=shortcut, client=client)

        handler.assert_not_called()
        client.views_open.assert_not_called()
        mock_resolve.assert_not_called()
        mock_notify.notify_error.assert_called_once()
        args = mock_notify.notify_error.call_args[0]
        assert args[0] == "C1"
        assert args[1] == "0.9"
        assert args[2] == "U1"
        assert "summarize_thread" in args[3]
        assert "SKILL.md" in args[3] or "install_skill_examples" in args[3]

    @patch("common.slack.slack_bot.slack_listener_with_threads.skill_folder_valid_for_forced_modal")
    @patch("common.slack.slack_bot.slack_listener_with_threads.resolve_copilot_slack_context")
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_shortcut_modal_submit_calls_handler(
        self, mock_slack_api, mock_resolve, mock_valid_folder,
    ):
        mock_valid_folder.return_value = True
        app = MagicMock()
        handler = MagicMock()
        msgs = [{"user": "U1", "text": "hello"}]
        mock_resolve.return_value = ("1516229200.000000", msgs)

        register_copilot_shortcut(app, handler)
        modal_fn = _get_registered_shortcut_modal_handler(app)

        body = {
            "view": {
                "private_metadata": json.dumps({
                    "skill_folder": "draft_with_copilot",
                    "channel_id": "C1",
                    "message_ts": "1516229207.000133",
                    "thread_ts": "1516229200.000000",
                    "user_id": "U1",
                    "channel_name": "team-chat",
                }),
                "state": {
                    "values": {
                        BLOCK_SHORTCUT_INSTRUCTION: {
                            ACTION_SHORTCUT_INSTRUCTION_TEXT: {
                                "value": "  Be brief.  ",
                            },
                        },
                    },
                },
            },
        }
        ack = MagicMock()
        modal_fn(ack=ack, body=body, _client=MagicMock())

        ack.assert_called_once_with()
        mock_resolve.assert_called_once_with(
            "C1",
            {"ts": "1516229207.000133", "thread_ts": "1516229200.000000"},
        )
        handler.assert_called_once_with(
            channel_id="C1",
            thread_ts="1516229200.000000",
            user_id="U1",
            user_text="Be brief.",
            thread_messages=msgs,
            channel_name="team-chat",
            context_kind="thread",
            copilot_trigger="message_shortcut",
            copilot_action="send_thread_reply_on_behalf_of_requester",
            forced_skill_folder="draft_with_copilot",
            anchor_message_text=None,
        )

    @patch("common.slack.slack_bot.slack_listener_with_threads.resolve_copilot_slack_context")
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_shortcut_modal_submit_invalid_metadata_errors(
        self, mock_slack_api, mock_resolve,
    ):
        app = MagicMock()
        handler = MagicMock()
        register_copilot_shortcut(app, handler)
        modal_fn = _get_registered_shortcut_modal_handler(app)
        ack = MagicMock()
        modal_fn(ack=ack, body={"view": {"private_metadata": "not-json"}}, _client=MagicMock())
        ack.assert_called_once_with(
            response_action="errors",
            errors={BLOCK_SHORTCUT_INSTRUCTION: "Invalid dialog state."},
        )
        handler.assert_not_called()
        mock_resolve.assert_not_called()

    @patch("common.slack.slack_bot.slack_listener_with_threads.load_forced_skill")
    @patch("common.slack.slack_bot.slack_listener_with_threads.skill_folder_valid_for_forced_modal")
    @patch("common.slack.slack_bot.slack_listener_with_threads.resolve_copilot_slack_context")
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_shortcut_modal_submit_empty_instruction_uses_default(
        self, mock_slack_api, mock_resolve, mock_valid_folder, mock_load_skill,
    ):
        mock_valid_folder.return_value = True
        mock_load_skill.return_value = ("draft_with_copilot", "# Draft thread reply\n")
        app = MagicMock()
        handler = MagicMock()
        mock_resolve.return_value = ("T1", [])

        register_copilot_shortcut(app, handler)
        modal_fn = _get_registered_shortcut_modal_handler(app)

        body = {
            "view": {
                "private_metadata": json.dumps({
                    "skill_folder": "draft_with_copilot",
                    "channel_id": "C1",
                    "message_ts": "1.0",
                    "user_id": "U1",
                }),
                "state": {
                    "values": {
                        BLOCK_SHORTCUT_INSTRUCTION: {
                            ACTION_SHORTCUT_INSTRUCTION_TEXT: {"value": "   "},
                        },
                    },
                },
            },
        }
        modal_fn(ack=MagicMock(), body=body, _client=MagicMock())
        handler.assert_called_once()
        assert handler.call_args[1]["user_text"] == (
            'user asked to trigger skill "Draft thread reply".'
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
        mock_slack_api.read_thread.return_value = [{"ts": "111.222"}]

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
        mock_slack_api.read_thread.assert_called_once_with("C9", "111.222")
        mock_slack_api.post_thread_message_as_app.assert_called_once_with(
            "C9", "111.222", "Starting thread...",
        )
        handler.assert_called_once_with(
            channel_id="C9",
            thread_ts="111.222",
            user_id="UHUMAN",
            user_text="make it brief",
            thread_messages=msgs,
            channel_name=None,
            context_kind="channel_tail",
            copilot_trigger="app_mention",
            copilot_action="send_thread_reply_on_behalf_of_requester",
            anchor_message_text="make it brief",
        )

    @patch("common.slack.slack_bot.slack_listener_with_threads.resolve_copilot_slack_context")
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_mention_root_skips_dummy_opener_when_thread_has_visible_replies(
        self, mock_slack_api, mock_resolve,
    ):
        app = MagicMock()
        handler = MagicMock()
        mock_resolve.return_value = ("111.222", [])
        mock_slack_api.read_thread.return_value = [
            {"ts": "111.222"},
            {"ts": "111.223"},
        ]

        register_copilot_app_mention(app, handler, bot_user_id="UBOT")
        registered_fn = _get_registered_app_mention_handler(app)

        registered_fn(event={
            "type": "app_mention",
            "channel": "C9",
            "user": "UHUMAN",
            "text": "<@UBOT> hi",
            "ts": "111.222",
        })

        mock_slack_api.read_thread.assert_called_once_with("C9", "111.222")
        mock_slack_api.post_thread_message_as_app.assert_not_called()
        handler.assert_called_once()

    @patch("common.slack.slack_bot.slack_listener_with_threads.resolve_copilot_slack_context")
    @patch("common.slack.slack_bot.slack_listener_with_threads.slack_api")
    def test_mention_root_posts_dummy_when_read_thread_fails(
        self, mock_slack_api, mock_resolve,
    ):
        app = MagicMock()
        handler = MagicMock()
        mock_resolve.return_value = ("111.222", [])
        mock_slack_api.read_thread.side_effect = RuntimeError("api down")

        register_copilot_app_mention(app, handler, bot_user_id="UBOT")
        registered_fn = _get_registered_app_mention_handler(app)

        registered_fn(event={
            "type": "app_mention",
            "channel": "C9",
            "user": "UHUMAN",
            "text": "<@UBOT> hi",
            "ts": "111.222",
        })

        mock_slack_api.read_thread.assert_called_once_with("C9", "111.222")
        mock_slack_api.post_thread_message_as_app.assert_called_once_with(
            "C9", "111.222", "Starting thread...",
        )
        handler.assert_called_once()

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
            copilot_action="send_thread_reply_on_behalf_of_requester",
            anchor_message_text="",
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
    @patch("common.slack.slack_bot.slack_listener_with_threads.copilot_user_notify")
    def test_mention_resolve_error_sends_ephemeral(self, mock_notify, mock_resolve):
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

        mock_notify.notify_error.assert_called_once_with(
            "C9", "6.0", "UHUMAN",
            "Add me to this channel first. /invite @CoPilot",
        )
