"""Send-thread-reply confirmation: Block Kit ephemeral, Revise modal, re-run ReAct loop."""

from __future__ import annotations

import json
from typing import Any

from slack_bolt import App

from common.log import log
from common.slack.slack_api import slack_api

from config.config import settings

_SLACK_BOT_CONFIG = settings.slack_bot
_PLAIN_CHUNK = _SLACK_BOT_CONFIG.get("block_kit_plain_text_chunk", 3000)
_MAX_BODY_BLOCKS = _SLACK_BOT_CONFIG.get("block_kit_max_body_blocks", 48)

BLOCK_HEADER = "reply_confirm_header"
BLOCK_BODY_PREFIX = "reply_body_"
BLOCK_ACTIONS = "reply_confirm_actions"
ACTION_REPLY_REVISE = "reply_confirm_revise"
CALLBACK_REPLY_REVISE_MODAL = "reply_confirm_revise_modal"
BLOCK_REVISE_INPUT = "revise_instruction_input"
ACTION_REVISE_TEXT = "revise_text"
BLOCK_INCLUDE_REPLY = "revise_include_reply"
ACTION_INCLUDE_REPLY = "include_reply_checkbox"

_PRIVATE_METADATA_LIMIT = _SLACK_BOT_CONFIG.get("private_metadata_limit", 3000)


class ReviseError(Exception):
    """User-visible Revise flow error."""


def _chunk_plain(message: str) -> list[str]:
    if not message:
        return []
    return [message[i : i + _PLAIN_CHUNK] for i in range(0, len(message), _PLAIN_CHUNK)]


def parse_reply_text_from_blocks(blocks: list[dict]) -> str:
    body_blocks = [
        b
        for b in blocks
        if str(b.get("block_id") or "").startswith(BLOCK_BODY_PREFIX)
    ]
    if not body_blocks:
        raise ReviseError("Could not read reply text from this message.")

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
        parts.append(str(txt.get("text") or ""))
    combined = "".join(parts)
    if not combined.strip():
        raise ReviseError("Could not read reply text from this message.")
    return combined


_BUTTON_VALUE_LIMIT = _SLACK_BOT_CONFIG.get("button_value_limit", 2000)


def _build_metadata_value(
    *,
    channel_id: str,
    anchor_ts: str,
    prepare_user_id: str,
    auth_user_id: str,
    context_kind: str,
    reply_text: str = "",
) -> str:
    payload: dict[str, Any] = {
        "channel_id": channel_id,
        "anchor_ts": anchor_ts,
        "prepare_user_id": prepare_user_id,
        "auth_user_id": auth_user_id,
        "context_kind": context_kind,
    }
    if reply_text:
        payload["reply_text"] = reply_text
    combined = json.dumps(payload, separators=(",", ":"))
    if len(combined) <= _BUTTON_VALUE_LIMIT:
        return combined
    overhead = len(
        json.dumps({**payload, "reply_text": ""}, separators=(",", ":"))
    )
    max_text = _BUTTON_VALUE_LIMIT - overhead - 3
    if max_text <= 0:
        payload.pop("reply_text", None)
        return json.dumps(payload, separators=(",", ":"))
    payload["reply_text"] = reply_text[:max_text] + "..."
    return json.dumps(payload, separators=(",", ":"))


def _parse_metadata(raw: str) -> dict[str, Any]:
    if not raw or not raw.strip():
        raise ReviseError("Missing revise context.")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ReviseError("Invalid revise context.") from e


def build_reply_confirmation_blocks(reply_text: str, metadata_value: str) -> list[dict]:
    chunks = _chunk_plain(reply_text)
    if len(chunks) > _MAX_BODY_BLOCKS:
        raise ValueError(
            f"Reply is too long for Revise UI ({len(reply_text)} chars; "
            f"max {_MAX_BODY_BLOCKS * _PLAIN_CHUNK})."
        )
    blocks: list[dict] = [
        {
            "type": "section",
            "block_id": BLOCK_HEADER,
            "text": {
                "type": "mrkdwn",
                "text": "*Suggested reply* \u2014 use *Revise* to edit the instruction and regenerate.",
            },
        }
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
                    "text": {"type": "plain_text", "text": "Revise"},
                    "action_id": ACTION_REPLY_REVISE,
                    "value": metadata_value[:_BUTTON_VALUE_LIMIT],
                }
            ],
        }
    )
    return blocks


@log
def send_reply_confirmation(
    channel_id: str,
    anchor_ts: str | None,
    recipient_user_id: str,
    prepare_user_id: str,
    reply_text: str,
    *,
    context_kind: str,
) -> None:
    meta = _build_metadata_value(
        channel_id=channel_id,
        anchor_ts=anchor_ts or "",
        prepare_user_id=prepare_user_id,
        auth_user_id=recipient_user_id,
        context_kind=context_kind,
        reply_text=reply_text,
    )
    if len(meta) > 2000:
        slack_api.send_ephemeral(
            channel_id,
            anchor_ts,
            recipient_user_id,
            "Revise metadata too large; sending plain reply.",
        )
        slack_api.send_ephemeral(channel_id, anchor_ts, recipient_user_id, reply_text)
        return
    try:
        blocks = build_reply_confirmation_blocks(reply_text, meta)
    except ValueError:
        slack_api.send_ephemeral(channel_id, anchor_ts, recipient_user_id, reply_text)
        return
    slack_api.send_ephemeral_blocks(
        channel_id,
        anchor_ts,
        recipient_user_id,
        "Suggested reply",
        blocks,
    )


def _build_private_metadata(metadata_json: str, reply_text: str) -> str:
    meta = json.loads(metadata_json)
    meta["reply_text"] = reply_text
    combined = json.dumps(meta, separators=(",", ":"))
    if len(combined) <= _PRIVATE_METADATA_LIMIT:
        return combined
    overhead = len(json.dumps({**meta, "reply_text": ""}, separators=(",", ":")))
    max_text = _PRIVATE_METADATA_LIMIT - overhead - 3
    meta["reply_text"] = reply_text[:max_text] + "..."
    return json.dumps(meta, separators=(",", ":"))


_INCLUDE_REPLY_OPTION = {
    "text": {
        "type": "plain_text",
        "text": "Include original reply suggestion in the revision prompt",
    },
    "value": "include",
}


def _build_revise_modal_view(reply_text: str, metadata_json: str) -> dict[str, Any]:
    return {
        "type": "modal",
        "callback_id": CALLBACK_REPLY_REVISE_MODAL,
        "private_metadata": _build_private_metadata(metadata_json, reply_text),
        "title": {"type": "plain_text", "text": "Revise reply", "emoji": True},
        "submit": {"type": "plain_text", "text": "Submit", "emoji": True},
        "close": {"type": "plain_text", "text": "Cancel", "emoji": True},
        "blocks": [
            {
                "type": "input",
                "block_id": BLOCK_REVISE_INPUT,
                "element": {
                    "type": "plain_text_input",
                    "action_id": ACTION_REVISE_TEXT,
                    "multiline": True,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "e.g. make it shorter, more formal...",
                    },
                },
                "label": {"type": "plain_text", "text": "Instruction", "emoji": True},
            },
            {
                "type": "input",
                "block_id": BLOCK_INCLUDE_REPLY,
                "optional": True,
                "element": {
                    "type": "checkboxes",
                    "action_id": ACTION_INCLUDE_REPLY,
                    "options": [_INCLUDE_REPLY_OPTION],
                    "initial_options": [_INCLUDE_REPLY_OPTION],
                },
                "label": {"type": "plain_text", "text": "Options", "emoji": True},
            },
        ],
    }


def _ephemeral_thread_ts(body: dict) -> str | None:
    msg = body.get("message") or {}
    return msg.get("thread_ts") or msg.get("ts")


def _reply_ephemeral_from_action(body: dict, text: str) -> None:
    channel_id = body["channel"]["id"]
    user_id = body["user"]["id"]
    thread_ts = _ephemeral_thread_ts(body)
    slack_api.send_ephemeral(channel_id, thread_ts, user_id, text)


def _checkbox_is_selected(values: dict[str, Any]) -> bool:
    cb_block = values.get(BLOCK_INCLUDE_REPLY) or {}
    cb_el = cb_block.get(ACTION_INCLUDE_REPLY) or {}
    selected = cb_el.get("selected_options") or []
    return len(selected) > 0


def _compose_revise_user_text(
    instruction: str, reply_text: str, include_reply: bool,
) -> str:
    if include_reply and reply_text:
        return (
            f"The original reply suggestion was:\n{reply_text}\n\n"
            f"The user requested a revision with this instruction:\n{instruction}"
        )
    return instruction


@log
def register_reply_confirmation_handlers(app: App) -> None:
    @app.action(ACTION_REPLY_REVISE)
    def _on_revise(ack, body, client):
        ack()
        try:
            action = (body.get("actions") or [{}])[0]
            raw_meta = action.get("value") or ""
            meta = _parse_metadata(raw_meta)
            clicker = body.get("user", {}).get("id") or ""
            if meta.get("auth_user_id") != clicker:
                _reply_ephemeral_from_action(body, "You can only revise your own reply.")
                return
            blocks = body.get("message", {}).get("blocks") or []
            try:
                reply_text = parse_reply_text_from_blocks(blocks)
            except ReviseError:
                reply_text = meta.get("reply_text") or ""
            if not reply_text.strip():
                raise ReviseError("Could not read reply text from this message.")
            view = _build_revise_modal_view(reply_text, raw_meta)
            client.views_open(trigger_id=body["trigger_id"], view=view)
        except ReviseError as e:
            _reply_ephemeral_from_action(body, str(e))
        except Exception:
            _reply_ephemeral_from_action(
                body, "Could not open revise dialog. Try again."
            )

    @app.view(CALLBACK_REPLY_REVISE_MODAL)
    def _on_modal_submit(ack, body, _client):
        view = body.get("view") or {}
        meta_raw = view.get("private_metadata") or ""
        user_id = body.get("user", {}).get("id") or ""
        try:
            meta = _parse_metadata(meta_raw)
        except ReviseError as e:
            ack(response_action="errors", errors={BLOCK_REVISE_INPUT: str(e)})
            return
        if meta.get("auth_user_id") != user_id:
            ack(
                response_action="errors",
                errors={BLOCK_REVISE_INPUT: "You cannot submit this revise."},
            )
            return
        values = view.get("state", {}).get("values", {})
        block = values.get(BLOCK_REVISE_INPUT) or {}
        el = block.get(ACTION_REVISE_TEXT) or {}
        instruction = (el.get("value") or "").strip()
        if not instruction:
            ack(
                response_action="errors",
                errors={BLOCK_REVISE_INPUT: "Enter an instruction or cancel."},
            )
            return
        ack()

        include_reply = _checkbox_is_selected(values)
        reply_text = meta.get("reply_text") or ""
        user_text = _compose_revise_user_text(instruction, reply_text, include_reply)

        channel_id = meta.get("channel_id") or ""
        anchor_ts = meta.get("anchor_ts") or None
        prepare_uid = meta.get("prepare_user_id") or ""
        channel_name = slack_api.get_channel_prefixed_name(channel_id)

        from common.slack.slack_bot.react_runner import run_react_and_confirm

        run_react_and_confirm(
            channel_id,
            anchor_ts or "",
            user_id,
            prepare_uid,
            user_text,
            context_kind=str(meta.get("context_kind") or "thread"),
            channel_name=channel_name,
            copilot_trigger="message_shortcut_revise",
            copilot_action="send_thread_reply",
        )
