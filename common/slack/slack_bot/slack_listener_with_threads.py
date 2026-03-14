from slack_bolt import App

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


def _extract_thread_ts(command: dict) -> str | None:
    return command.get("thread_ts") or command.get("message_ts")
