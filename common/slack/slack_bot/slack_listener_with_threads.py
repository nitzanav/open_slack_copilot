import re

from slack_bolt import App

from common.log import log
from common.slack.copilot_pipeline import ThreadFetchError, resolve_copilot_slack_context
from common.slack.slack_api import slack_api
from common.slack.slack_bot import dm_confirmation

register_dm_confirmation_handlers = dm_confirmation.register_dm_confirmation_handlers

_MENTION_TOKEN_RE = re.compile(r"<@[^>]+>\s*")


def _strip_app_mention_tokens(text: str) -> str:
    return _MENTION_TOKEN_RE.sub("", text or "").strip()


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
        response_url = shortcut.get("response_url")
        anchor_fallback = message.get("thread_ts") or message["ts"]

        try:
            anchor_ts, thread_messages = resolve_copilot_slack_context(channel_id, message)
        except ThreadFetchError:
            _send_channel_error(channel_id, anchor_fallback, user_id, response_url)
            return

        handler(
            channel_id=channel_id,
            thread_ts=anchor_ts,
            user_id=user_id,
            user_text="",
            thread_messages=thread_messages,
            channel_name=shortcut["channel"].get("name"),
        )


def register_copilot_app_mention(app: App, handler, bot_user_id: str | None = None):

    @app.event("app_mention")
    @log
    def handle_app_mention(event):
        if event.get("subtype"):
            return
        if bot_user_id and event.get("user") == bot_user_id:
            return
        channel_id = event["channel"]
        user_id = event["user"]
        user_text = _strip_app_mention_tokens(event.get("text", ""))
        message = {"ts": event["ts"]}
        if event.get("thread_ts"):
            message["thread_ts"] = event["thread_ts"]
        anchor_fallback = event.get("thread_ts") or event["ts"]

        try:
            anchor_ts, thread_messages = resolve_copilot_slack_context(channel_id, message)
        except ThreadFetchError:
            slack_api.send_ephemeral(
                channel_id,
                anchor_fallback,
                user_id,
                "Add me to this channel first. /invite @CoPilot",
            )
            return

        handler(
            channel_id=channel_id,
            thread_ts=anchor_ts,
            user_id=user_id,
            user_text=user_text,
            thread_messages=thread_messages,
            channel_name=None,
        )


def _extract_thread_ts(command: dict) -> str | None:
    return command.get("thread_ts") or command.get("message_ts")


def _send_channel_error(channel_id: str, thread_ts: str, user_id: str,
                       response_url: str | None):
    msg = "Add me to this channel first. /invite @CoPilot"
    try:
        slack_api.send_ephemeral(channel_id, thread_ts, user_id, msg)
        return
    except Exception:
        pass
    if response_url:
        try:
            slack_api.respond_ephemeral(response_url, msg)
        except Exception:
            pass
