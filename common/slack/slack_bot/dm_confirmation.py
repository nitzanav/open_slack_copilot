"""DM send confirmation: full message is shown in Slack blocks; Send reads it back from the signed interaction payload (no server-side pending map)."""

from __future__ import annotations

from slack_bolt import App

from common.log import log
from common.slack.slack_api import slack_api
from config.config import settings

# Slack Block Kit: plain_text in a section is max 3000 chars; max 50 blocks per message.
_PLAIN_CHUNK = 3000
_MAX_BODY_BLOCKS = 48  # header + actions + body <= 50

BLOCK_HEADER = "dm_confirm_header"
BLOCK_BODY_PREFIX = "dm_confirm_body_"
BLOCK_ACTIONS = "dm_confirm_actions"


def _owner_id() -> str | None:
    oid = str(settings.slack_bot.get("config_owner_user_id") or "").strip()
    return oid or None


def _chunk_plain_text(message: str) -> list[str]:
    if not message:
        return []
    return [message[i : i + _PLAIN_CHUNK] for i in range(0, len(message), _PLAIN_CHUNK)]


def parse_message_from_confirmation_blocks(blocks: list[dict]) -> tuple[str | None, str | None]:
    """Return (message, error). Message is concatenation of dm_confirm_body_* section texts."""
    body_blocks = [
        b
        for b in blocks
        if str(b.get("block_id") or "").startswith(BLOCK_BODY_PREFIX)
    ]
    if not body_blocks:
        return None, "Could not read message from confirmation."

    def sort_key(b: dict) -> int:
        bid = str(b.get("block_id") or "")
        try:
            return int(bid.split("_")[-1])
        except (ValueError, IndexError):
            return 0

    body_blocks.sort(key=sort_key)
    parts: list[str] = []
    for b in body_blocks:
        txt = b.get("text") or {}
        if txt.get("type") == "plain_text":
            parts.append(str(txt.get("text") or ""))
        elif txt.get("type") == "mrkdwn":
            parts.append(str(txt.get("text") or ""))
    combined = "".join(parts)
    if not combined:
        return None, "Could not read message from confirmation."
    return combined, None


def _build_confirmation_blocks(
    target_label: str, message: str, target_user_id: str
) -> tuple[list[dict] | None, str | None]:
    """Returns (blocks, error_message)."""
    chunks = _chunk_plain_text(message)
    if len(chunks) > _MAX_BODY_BLOCKS:
        return None, (
            f"Message is too long to confirm in Slack ({len(message)} chars; "
            f"max {_MAX_BODY_BLOCKS * _PLAIN_CHUNK})."
        )

    blocks: list[dict] = [
        {
            "type": "section",
            "block_id": BLOCK_HEADER,
            "text": {
                "type": "mrkdwn",
                "text": f"*Confirm direct message*\n*To:* {target_label}",
            },
        },
    ]
    for i, chunk in enumerate(chunks):
        blocks.append(
            {
                "type": "section",
                "block_id": f"{BLOCK_BODY_PREFIX}{i}",
                "text": {"type": "plain_text", "text": chunk, "emoji": False},
            }
        )
    blocks.append(
        {
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
    )
    return blocks, None


@log
def suggest_sending_dm(
    target_user_id: str,
    message: str,
    channel_id: str,
    thread_ts: str | None,
    target_label: str,
) -> str:
    owner = _owner_id()
    if not owner:
        return "Error: slack_bot.config_owner_user_id is not set; cannot queue DM confirmation."

    blocks, err = _build_confirmation_blocks(target_label, message, target_user_id)
    if err:
        return f"Error: {err}"
    assert blocks is not None

    slack_api.send_ephemeral_blocks(
        channel_id, thread_ts, owner, "Confirm direct message", blocks
    )
    return "DM queued for confirmation"


@log
def handle_send_action(body: dict) -> str:
    owner = _owner_id()
    clicker = body.get("user", {}).get("id")
    if owner and clicker and clicker != owner:
        return "Only the configured owner can confirm this DM."

    target_user_id = (body.get("actions") or [{}])[0].get("value") or ""
    if not target_user_id:
        return "Missing recipient for this confirmation."

    blocks = body.get("message", {}).get("blocks") or []
    msg, parse_err = parse_message_from_confirmation_blocks(blocks)
    if parse_err:
        return parse_err
    assert msg is not None

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
        channel_id = body["channel"]["id"]
        user_id = body["user"]["id"]
        thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")
        slack_api.send_ephemeral(channel_id, thread_ts, user_id, result)

    @app.action("dm_confirm_cancel")
    def _on_cancel(ack, body, _client):
        ack()
        result = handle_cancel_action(body)
        channel_id = body["channel"]["id"]
        user_id = body["user"]["id"]
        thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")
        slack_api.send_ephemeral(channel_id, thread_ts, user_id, result)


def clear_pending_for_tests():
    """No-op: pending state was removed; kept for any legacy test hooks."""
    pass
