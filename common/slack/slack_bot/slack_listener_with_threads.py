from slack_bolt import App

from common.log import log
from common.slack.slack_api import slack_api


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

        try:
            thread_messages = slack_api.read_thread(channel_id, thread_ts)
        except Exception:
            slack_api.send_ephemeral(channel_id, thread_ts, user_id, "Add me to this channel first.")
            return

        handler(
            channel_id=channel_id,
            thread_ts=thread_ts,
            user_id=user_id,
            user_text=user_text,
            thread_messages=thread_messages,
        )


def register_copilot_shortcut(app: App, handler):

    @app.shortcut({"callback_id": "draft_with_copilot", "type": "message_action"})
    @log
    def handle_draft_shortcut(ack, shortcut, client):
        ack()
        channel_id = shortcut["channel"]["id"]
        user_id = shortcut["user"]["id"]
        message = shortcut["message"]
        thread_ts = message.get("thread_ts") or message["ts"]
        response_url = shortcut.get("response_url")

        try:
            thread_messages = slack_api.read_thread(channel_id, thread_ts)
        except Exception:
            _send_channel_error(channel_id, thread_ts, user_id, response_url)
            return

        handler(
            channel_id=channel_id,
            thread_ts=thread_ts,
            user_id=user_id,
            user_text="",
            thread_messages=thread_messages,
        )


def _extract_thread_ts(command: dict) -> str | None:
    return command.get("thread_ts") or command.get("message_ts")


def _send_channel_error(channel_id: str, thread_ts: str, user_id: str,
                       response_url: str | None):
    msg = "Add me to this channel first."
    if response_url:
        try:
            slack_api.respond_ephemeral(response_url, msg)
            return
        except Exception:
            pass
    try:
        slack_api.send_ephemeral(channel_id, thread_ts, user_id, msg)
    except Exception:
        pass
