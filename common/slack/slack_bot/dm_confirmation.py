"""DM send confirmation via Slack Block Kit ephemeral messages."""

from __future__ import annotations

from slack_bolt import App

from common.log import log
from common.slack.slack_api import slack_api
from config.config import settings

_SLACK_BOT_CONFIG = settings.slack_bot
_PLAIN_CHUNK = _SLACK_BOT_CONFIG.get("block_kit_plain_text_chunk", 3000)  # Slack plain_text section max
_MAX_BODY_BLOCKS = _SLACK_BOT_CONFIG.get("block_kit_max_body_blocks", 48)  # header + actions + body <= 50

BLOCK_HEADER = "dm_confirm_header"
BLOCK_BODY_PREFIX = "dm_confirm_body_"
BLOCK_ACTIONS = "dm_confirm_actions"


# ---------------------------------------------------------------------------
# Parsing confirmation blocks back into message text
# ---------------------------------------------------------------------------

def parse_message_from_confirmation_blocks(blocks: list[dict]) -> str:
    body_blocks = _filter_body_blocks(blocks)
    sorted_blocks = _sort_by_block_index(body_blocks)
    return _join_block_texts(sorted_blocks)


def _filter_body_blocks(blocks: list[dict]) -> list[dict]:
    out = [b for b in blocks if str(b.get("block_id") or "").startswith(BLOCK_BODY_PREFIX)]
    if not out:
        raise _ConfirmationParseError("Could not read message from confirmation.")
    return out


def _sort_by_block_index(blocks: list[dict]) -> list[dict]:
    def index(b: dict) -> int:
        try:
            return int(str(b.get("block_id") or "").split("_")[-1])
        except (ValueError, IndexError):
            return 0
    return sorted(blocks, key=index)


def _join_block_texts(blocks: list[dict]) -> str:
    parts = [str((b.get("text") or {}).get("text") or "") for b in blocks]
    combined = "".join(parts)
    if not combined:
        raise _ConfirmationParseError("Could not read message from confirmation.")
    return combined


class _ConfirmationParseError(Exception):
    pass


# ---------------------------------------------------------------------------
# Building confirmation blocks
# ---------------------------------------------------------------------------

def _build_confirmation_blocks(
    target_label: str, message: str, target_user_id: str
) -> list[dict]:
    body = _message_body_blocks(message)
    return [
        _header_block(target_label),
        *body,
        _actions_block(target_user_id),
    ]


def _header_block(target_label: str) -> dict:
    return {
        "type": "section",
        "block_id": BLOCK_HEADER,
        "text": {"type": "mrkdwn", "text": f"*Confirm direct message*\n*To:* {target_label}"},
    }


def _message_body_blocks(message: str) -> list[dict]:
    chunks = [message[i : i + _PLAIN_CHUNK] for i in range(0, len(message), _PLAIN_CHUNK)] if message else []
    if len(chunks) > _MAX_BODY_BLOCKS:
        raise ValueError(
            f"Message is too long to confirm in Slack ({len(message)} chars; "
            f"max {_MAX_BODY_BLOCKS * _PLAIN_CHUNK})."
        )
    return [
        {
            "type": "section",
            "block_id": f"{BLOCK_BODY_PREFIX}{i}",
            "text": {"type": "plain_text", "text": chunk, "emoji": False},
        }
        for i, chunk in enumerate(chunks)
    ]


def _actions_block(target_user_id: str) -> dict:
    return {
        "type": "actions",
        "block_id": BLOCK_ACTIONS,
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Send"},
                "style": "primary",
                "action_id": "dm_confirm_send",
                "value": target_user_id,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Cancel"},
                "action_id": "dm_confirm_cancel",
                "value": "cancel",
            },
        ],
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@log
def suggest_sending_dm(
    target_user_id: str,
    message: str,
    channel_id: str,
    thread_ts: str | None,
    target_label: str,
    requester_user_id: str = "",
) -> str:
    recipient = requester_user_id or ""
    if not recipient:
        return "Error: requester_user_id is required to send DM confirmation."
    try:
        blocks = _build_confirmation_blocks(target_label, message, target_user_id)
    except ValueError as e:
        return f"Error: {e}"
    slack_api.send_ephemeral_blocks(
        channel_id, thread_ts, recipient, "Confirm direct message", blocks
    )
    return "DM queued for confirmation"


@log
def handle_send_action(body: dict) -> str:
    target_user_id = (body.get("actions") or [{}])[0].get("value") or ""
    if not target_user_id:
        return "Missing recipient for this confirmation."

    blocks = body.get("message", {}).get("blocks") or []
    try:
        msg = parse_message_from_confirmation_blocks(blocks)
    except _ConfirmationParseError as e:
        return str(e)

    try:
        slack_api.send_dm(target_user_id, msg)
    except Exception as e:
        return f"Failed to send DM: {e}"
    return "DM sent."


@log
def handle_cancel_action(_body: dict) -> str:
    return "DM cancelled."


def register_dm_confirmation_handlers(app: App):
    @app.action("dm_confirm_send")
    def _on_send(ack, body, _client):
        ack()
        result = handle_send_action(body)
        _reply_ephemeral(body, result)

    @app.action("dm_confirm_cancel")
    def _on_cancel(ack, body, _client):
        ack()
        result = handle_cancel_action(body)
        _reply_ephemeral(body, result)


def _reply_ephemeral(body: dict, text: str):
    channel_id = body["channel"]["id"]
    user_id = body["user"]["id"]
    thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")
    slack_api.send_ephemeral(channel_id, thread_ts, user_id, text)
