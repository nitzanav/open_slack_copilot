"""Ephemeral draft + Revise: Block Kit, modal, re-run prepare_draft with same Slack context."""

from __future__ import annotations

import json
from typing import Any

from slack_bolt import App

from common.log import log
from common.slack.copilot_pipeline import (
    ThreadFetchError,
    fetch_channel_tail_messages,
    fetch_thread_messages,
    prepare_draft,
)
from common.slack.slack_api import slack_api

_PLAIN_CHUNK = 3000
_MAX_BODY_BLOCKS = 48

BLOCK_HEADER = "draft_rev_header"
BLOCK_BODY_PREFIX = "draft_body_"
BLOCK_ACTIONS = "draft_revise_actions"
ACTION_DRAFT_REVISE = "draft_revise"
CALLBACK_DRAFT_REVISE_MODAL = "draft_revise_modal"
BLOCK_REVISE_INPUT = "revise_instruction_input"
ACTION_REVISE_TEXT = "revise_text"
BLOCK_INCLUDE_DRAFT = "revise_include_draft"
ACTION_INCLUDE_DRAFT = "include_draft_checkbox"

_PRIVATE_METADATA_LIMIT = 3000


class DraftReviseError(Exception):
    """User-visible Revise flow error."""


def _chunk_plain(message: str) -> list[str]:
    if not message:
        return []
    return [message[i : i + _PLAIN_CHUNK] for i in range(0, len(message), _PLAIN_CHUNK)]


def parse_draft_from_revise_blocks(blocks: list[dict]) -> str:
    body_blocks = [
        b
        for b in blocks
        if str(b.get("block_id") or "").startswith(BLOCK_BODY_PREFIX)
    ]
    if not body_blocks:
        raise DraftReviseError("Could not read draft text from this message.")

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
        raise DraftReviseError("Could not read draft text from this message.")
    return combined


_BUTTON_VALUE_LIMIT = 2000


def _build_metadata_value(
    *,
    channel_id: str,
    anchor_ts: str,
    prepare_user_id: str,
    auth_user_id: str,
    context_kind: str,
    draft: str = "",
) -> str:
    payload: dict[str, Any] = {
        "channel_id": channel_id,
        "anchor_ts": anchor_ts,
        "prepare_user_id": prepare_user_id,
        "auth_user_id": auth_user_id,
        "context_kind": context_kind,
    }
    if draft:
        payload["draft"] = draft
    combined = json.dumps(payload, separators=(",", ":"))
    if len(combined) <= _BUTTON_VALUE_LIMIT:
        return combined
    overhead = len(
        json.dumps({**payload, "draft": ""}, separators=(",", ":"))
    )
    max_draft = _BUTTON_VALUE_LIMIT - overhead - 3
    if max_draft <= 0:
        payload.pop("draft", None)
        return json.dumps(payload, separators=(",", ":"))
    payload["draft"] = draft[:max_draft] + "..."
    return json.dumps(payload, separators=(",", ":"))


def _parse_metadata(raw: str) -> dict[str, Any]:
    if not raw or not raw.strip():
        raise DraftReviseError("Missing revise context.")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise DraftReviseError("Invalid revise context.") from e


def build_draft_revise_blocks(draft_text: str, metadata_value: str) -> list[dict]:
    chunks = _chunk_plain(draft_text)
    if len(chunks) > _MAX_BODY_BLOCKS:
        raise ValueError(
            f"Draft is too long for Revise UI ({len(draft_text)} chars; "
            f"max {_MAX_BODY_BLOCKS * _PLAIN_CHUNK})."
        )
    blocks: list[dict] = [
        {
            "type": "section",
            "block_id": BLOCK_HEADER,
            "text": {
                "type": "mrkdwn",
                "text": "*Suggested reply* — use *Revise* to edit the instruction and regenerate.",
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
                    "action_id": ACTION_DRAFT_REVISE,
                    "value": metadata_value[:_BUTTON_VALUE_LIMIT],
                }
            ],
        }
    )
    return blocks


@log
def send_draft_ephemeral_with_revise(
    channel_id: str,
    anchor_ts: str | None,
    recipient_user_id: str,
    prepare_user_id: str,
    draft_text: str,
    *,
    context_kind: str,
) -> None:
    meta = _build_metadata_value(
        channel_id=channel_id,
        anchor_ts=anchor_ts or "",
        prepare_user_id=prepare_user_id,
        auth_user_id=recipient_user_id,
        context_kind=context_kind,
        draft=draft_text,
    )
    if len(meta) > 2000:
        slack_api.send_ephemeral(
            channel_id,
            anchor_ts,
            recipient_user_id,
            "Revise metadata too large; sending plain draft.",
        )
        slack_api.send_ephemeral(channel_id, anchor_ts, recipient_user_id, draft_text)
        return
    try:
        blocks = build_draft_revise_blocks(draft_text, meta)
    except ValueError:
        slack_api.send_ephemeral(channel_id, anchor_ts, recipient_user_id, draft_text)
        return
    slack_api.send_ephemeral_blocks(
        channel_id,
        anchor_ts,
        recipient_user_id,
        "Suggested reply",
        blocks,
    )


def _resolve_thread_messages(meta: dict[str, Any]) -> list[dict]:
    channel_id = meta.get("channel_id") or ""
    anchor_ts = meta.get("anchor_ts") or ""
    kind = meta.get("context_kind") or "thread"
    if kind == "channel_tail":
        return fetch_channel_tail_messages(channel_id)
    if not anchor_ts:
        raise DraftReviseError("Missing thread anchor for revise.")
    return fetch_thread_messages(channel_id, anchor_ts)


def _build_private_metadata(metadata_json: str, draft: str) -> str:
    meta = json.loads(metadata_json)
    meta["draft"] = draft
    combined = json.dumps(meta, separators=(",", ":"))
    if len(combined) <= _PRIVATE_METADATA_LIMIT:
        return combined
    overhead = len(json.dumps({**meta, "draft": ""}, separators=(",", ":")))
    max_draft = _PRIVATE_METADATA_LIMIT - overhead - 3
    meta["draft"] = draft[:max_draft] + "..."
    return json.dumps(meta, separators=(",", ":"))


_INCLUDE_DRAFT_OPTION = {
    "text": {
        "type": "plain_text",
        "text": "Include original reply suggestion in the revision prompt",
    },
    "value": "include",
}


def _build_revise_modal_view(draft: str, metadata_json: str) -> dict[str, Any]:
    return {
        "type": "modal",
        "callback_id": CALLBACK_DRAFT_REVISE_MODAL,
        "private_metadata": _build_private_metadata(metadata_json, draft),
        "title": {"type": "plain_text", "text": "Revise draft", "emoji": True},
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
                "block_id": BLOCK_INCLUDE_DRAFT,
                "optional": True,
                "element": {
                    "type": "checkboxes",
                    "action_id": ACTION_INCLUDE_DRAFT,
                    "options": [_INCLUDE_DRAFT_OPTION],
                    "initial_options": [_INCLUDE_DRAFT_OPTION],
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
    cb_block = values.get(BLOCK_INCLUDE_DRAFT) or {}
    cb_el = cb_block.get(ACTION_INCLUDE_DRAFT) or {}
    selected = cb_el.get("selected_options") or []
    return len(selected) > 0


def _compose_revise_user_text(
    instruction: str, draft: str, include_draft: bool,
) -> str:
    if include_draft and draft:
        return (
            f"The original reply suggestion was:\n{draft}\n\n"
            f"The user requested a revision with this instruction:\n{instruction}"
        )
    return instruction


@log
def register_draft_revise_handlers(app: App) -> None:
    @app.action(ACTION_DRAFT_REVISE)
    def _on_revise(ack, body, client):
        ack()
        try:
            action = (body.get("actions") or [{}])[0]
            raw_meta = action.get("value") or ""
            meta = _parse_metadata(raw_meta)
            clicker = body.get("user", {}).get("id") or ""
            if meta.get("auth_user_id") != clicker:
                _reply_ephemeral_from_action(body, "You can only revise your own draft.")
                return
            blocks = body.get("message", {}).get("blocks") or []
            try:
                draft = parse_draft_from_revise_blocks(blocks)
            except DraftReviseError:
                draft = meta.get("draft") or ""
            if not draft.strip():
                raise DraftReviseError("Could not read draft text from this message.")
            view = _build_revise_modal_view(draft, raw_meta)
            client.views_open(trigger_id=body["trigger_id"], view=view)
        except DraftReviseError as e:
            _reply_ephemeral_from_action(body, str(e))
        except Exception:
            _reply_ephemeral_from_action(
                body, "Could not open revise dialog. Try again."
            )

    @app.view(CALLBACK_DRAFT_REVISE_MODAL)
    def _on_modal_submit(ack, body, _client):
        view = body.get("view") or {}
        meta_raw = view.get("private_metadata") or ""
        user_id = body.get("user", {}).get("id") or ""
        try:
            meta = _parse_metadata(meta_raw)
        except DraftReviseError as e:
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

        include_draft = _checkbox_is_selected(values)
        draft_text = meta.get("draft") or ""
        user_text = _compose_revise_user_text(instruction, draft_text, include_draft)

        channel_id = meta.get("channel_id") or ""
        anchor_ts = meta.get("anchor_ts") or None
        prepare_uid = meta.get("prepare_user_id") or ""
        channel_name = slack_api.get_channel_prefixed_name(channel_id)

        try:
            thread_messages = _resolve_thread_messages(meta)
        except ThreadFetchError:
            slack_api.send_ephemeral(
                channel_id,
                anchor_ts,
                user_id,
                "Add me to this channel first. /invite @CoPilot",
            )
            return
        except DraftReviseError as e:
            slack_api.send_ephemeral(channel_id, anchor_ts, user_id, str(e))
            return

        try:
            new_draft = prepare_draft(
                channel_id,
                anchor_ts or "",
                prepare_uid,
                user_text,
                channel_name=channel_name,
                thread_messages=thread_messages,
                copilot_trigger="message_shortcut_revise",
                copilot_action="suggested_draft",
            )
        except ThreadFetchError:
            slack_api.send_ephemeral(
                channel_id,
                anchor_ts,
                user_id,
                "Add me to this channel first. /invite @CoPilot",
            )
            return
        except Exception:
            slack_api.send_ephemeral(
                channel_id,
                anchor_ts,
                user_id,
                "Failed to generate draft, try again.",
            )
            return

        send_draft_ephemeral_with_revise(
            channel_id,
            anchor_ts,
            user_id,
            prepare_uid,
            new_draft,
            context_kind=str(meta.get("context_kind") or "thread"),
        )
