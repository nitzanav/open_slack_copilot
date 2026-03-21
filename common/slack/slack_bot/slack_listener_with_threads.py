from slack_bolt import App

from common.log import log
from common.slack.slack_api import slack_api
from common.slack.slack_bot import dm_confirmation

register_dm_confirmation_handlers = dm_confirmation.register_dm_confirmation_handlers


def register_copilot_command(app: App, handler):

    @app.command("/copilot")
    def handle_copilot(ack, command):
        ack()
        channel_id = command["channel_id"]
        user_id = command["user_id"]
        user_text = command.get("text", "")

        thread_ts = _extract_thread_ts(command)
        if not thread_ts:
            slack_api.send_ephemeral(channel_id, None, user_id, "Use /copilot inside a thread.")
            return

        handler(
            channel_id=channel_id,
            thread_ts=thread_ts,
            user_id=user_id,
            user_text=user_text,
            channel_name=command.get("channel_name"),
        )


def register_copilot_shortcut(app: App, handler):

    @app.shortcut("draft_with_copilot")
    @log
    def handle_draft_shortcut(ack, shortcut, client):
        ack()
        channel_id = shortcut["channel"]["id"]
        user_id = shortcut["user"]["id"]
        message = shortcut["message"]
        thread_ts = message.get("thread_ts") or message["ts"]

        handler(
            channel_id=channel_id,
            thread_ts=thread_ts,
            user_id=user_id,
            user_text="",
            channel_name=shortcut["channel"].get("name"),
        )


def _extract_thread_ts(command: dict) -> str | None:
    return command.get("thread_ts") or command.get("message_ts")
