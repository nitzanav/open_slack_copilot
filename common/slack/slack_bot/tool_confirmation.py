"""User confirmation for tools that require it (Slack Block Kit ephemerals)."""

from __future__ import annotations

import json
from typing import Any

from slack_bolt import App

from common.log import log
from common.slack.slack_api import slack_api
from common.tools.copilot_tool import (
    ToolConfirmationSpec,
    get_copilot_tool,
    get_tool_confirmation_spec,
)
from config.config import settings

_SLACK_BOT_CONFIG = settings.slack_bot
_PLAIN_CHUNK = _SLACK_BOT_CONFIG.get("block_kit_plain_text_chunk", 3000)
_MAX_BODY_BLOCKS = _SLACK_BOT_CONFIG.get("block_kit_max_body_blocks", 48)
_BUTTON_VALUE_LIMIT = _SLACK_BOT_CONFIG.get("button_value_limit", 2000)
_PRIVATE_METADATA_LIMIT = _SLACK_BOT_CONFIG.get("private_metadata_limit", 3000)

BLOCK_HEADER = "tool_confirm_header"
BLOCK_BODY_PREFIX = "tool_confirm_body_"
BLOCK_ACTIONS = "tool_confirm_actions"
ACTION_TOOL_CONFIRM = "tool_confirm_action"
ACTION_TOOL_REVISE = "tool_confirm_revise"
CALLBACK_TOOL_CONFIRM_REVISE_MODAL = "tool_confirm_revise_modal"
BLOCK_REVISE_INPUT = "tool_confirm_revise_input"
ACTION_REVISE_TEXT = "tool_confirm_revise_text"
BLOCK_INCLUDE_TEXT = "tool_confirm_include_text"
ACTION_INCLUDE_TEXT = "tool_confirm_include_text_cb"

_INCLUDE_TEXT_OPTION = {
    "text": {
        "type": "plain_text",
        "text": "Include original text in the revision prompt",
    },
    "value": "include",
}


class _ConfirmationParseError(Exception):
    pass


def parse_text_from_confirmation_blocks(blocks: list[dict], text_param_key: str) -> str:
    del text_param_key  # reserved for multi-param layouts; body is always chunked text
    body_blocks = [
        b for b in blocks if str(b.get("block_id") or "").startswith(BLOCK_BODY_PREFIX)
    ]
    if not body_blocks:
        raise _ConfirmationParseError("Could not read text from this confirmation.")

    def sort_key(b: dict) -> int:
        bid = str(b.get("block_id") or "")
        try:
            return int(bid.split("_")[-1])
        except (ValueError, IndexError):
            return 0

    body_blocks.sort(key=sort_key)
    parts = [str((b.get("text") or {}).get("text") or "") for b in body_blocks]
    combined = "".join(parts)
    if not combined:
        raise _ConfirmationParseError("Could not read text from this confirmation.")
    return combined


def _message_body_blocks(text: str) -> list[dict]:
    chunks = (
        [text[i : i + _PLAIN_CHUNK] for i in range(0, len(text), _PLAIN_CHUNK)]
        if text
        else []
    )
    if len(chunks) > _MAX_BODY_BLOCKS:
        raise ValueError(
            f"Text is too long to confirm in Slack ({len(text)} chars; "
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


def _extra_params_section(spec: ToolConfirmationSpec, payload: dict[str, Any]) -> list[dict]:
    keys = spec.extra_param_keys_to_display
    if not keys:
        return []
    subset = {k: payload.get(k) for k in keys if k in payload}
    if not any(v is not None for v in subset.values()):
        return []
    pretty = json.dumps(subset, indent=2, ensure_ascii=False)
    return [
        {
            "type": "section",
            "block_id": "tool_confirm_extra_params",
            "text": {"type": "mrkdwn", "text": f"```{pretty}```"},
        }
    ]


def _build_confirmation_blocks(
    tool_name: str,
    spec: ToolConfirmationSpec,
    text_content: str,
    payload: dict[str, Any],
) -> list[dict]:
    body = _message_body_blocks(text_content)
    return [
        {
            "type": "section",
            "block_id": BLOCK_HEADER,
            "text": {"type": "mrkdwn", "text": spec.confirmation_header_markdown},
        },
        *_extra_params_section(spec, payload),
        *body,
        _actions_block(tool_name, payload),
    ]


def _compact_revise_metadata(meta: dict[str, Any]) -> str:
    combined = json.dumps(meta, separators=(",", ":"))
    if len(combined) <= _BUTTON_VALUE_LIMIT:
        return combined
    payload = meta.get("payload")
    if isinstance(payload, dict):
        trimmed = {**meta, "payload": dict(payload)}
        for k, v in list(trimmed["payload"].items()):
            if isinstance(v, str) and len(v) > 500:
                trimmed["payload"][k] = v[:500] + "..."
        combined = json.dumps(trimmed, separators=(",", ":"))
        if len(combined) <= _BUTTON_VALUE_LIMIT:
            return combined
    raise ValueError("Confirmation context is too large for Revise.")


def _actions_block(tool_name: str, payload: dict[str, Any]) -> dict:
    meta = {
        "v": 1,
        "tool_name": tool_name,
        "payload": payload,
    }
    revise_value = _compact_revise_metadata(meta)
    confirm_raw = json.dumps(meta, separators=(",", ":"))
    if len(confirm_raw) > _BUTTON_VALUE_LIMIT:
        raise ValueError("Confirmation context is too large for Confirm button.")
    return {
        "type": "actions",
        "block_id": BLOCK_ACTIONS,
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Revise"},
                "action_id": ACTION_TOOL_REVISE,
                "value": revise_value,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Confirm"},
                "style": "primary",
                "action_id": ACTION_TOOL_CONFIRM,
                "value": confirm_raw,
            },
        ],
    }


def _parse_revise_metadata(raw: str) -> dict[str, Any]:
    if not raw or not str(raw).strip():
        raise ValueError("Missing confirmation context.")
    try:
        meta = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError("Invalid confirmation context.") from e
    if meta.get("v") != 1 or not meta.get("tool_name"):
        raise ValueError("Invalid confirmation context.")
    return meta


def _ephemeral_thread_ts(body: dict) -> str | None:
    msg = body.get("message") or {}
    return msg.get("thread_ts") or msg.get("ts")


def _reply_ephemeral_from_action(body: dict, text: str) -> None:
    channel_id = body["channel"]["id"]
    user_id = body["user"]["id"]
    thread_ts = _ephemeral_thread_ts(body)
    slack_api.send_ephemeral(channel_id, thread_ts, user_id, text)


def _build_private_metadata(metadata_json: str, tool_text: str) -> str:
    meta = json.loads(metadata_json)
    meta["tool_text"] = tool_text
    combined = json.dumps(meta, separators=(",", ":"))
    if len(combined) <= _PRIVATE_METADATA_LIMIT:
        return combined
    overhead = len(json.dumps({**meta, "tool_text": ""}, separators=(",", ":")))
    max_t = _PRIVATE_METADATA_LIMIT - overhead - 3
    meta["tool_text"] = tool_text[:max_t] + "..."
    return json.dumps(meta, separators=(",", ":"))


def _build_tool_revise_modal_view(tool_text: str, metadata_json: str) -> dict[str, Any]:
    return {
        "type": "modal",
        "callback_id": CALLBACK_TOOL_CONFIRM_REVISE_MODAL,
        "private_metadata": _build_private_metadata(metadata_json, tool_text),
        "title": {"type": "plain_text", "text": "Revise action", "emoji": True},
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
                        "text": "e.g. make it shorter, change the tone...",
                    },
                },
                "label": {"type": "plain_text", "text": "Instruction", "emoji": True},
            },
            {
                "type": "input",
                "block_id": BLOCK_INCLUDE_TEXT,
                "optional": True,
                "element": {
                    "type": "checkboxes",
                    "action_id": ACTION_INCLUDE_TEXT,
                    "options": [_INCLUDE_TEXT_OPTION],
                    "initial_options": [_INCLUDE_TEXT_OPTION],
                },
                "label": {"type": "plain_text", "text": "Options", "emoji": True},
            },
        ],
    }


def _checkbox_include_text_selected(values: dict[str, Any]) -> bool:
    block = values.get(BLOCK_INCLUDE_TEXT) or {}
    el = block.get(ACTION_INCLUDE_TEXT) or {}
    return len(el.get("selected_options") or []) > 0


def _compose_tool_revise_user_text(
    instruction: str, tool_text: str, include_text: bool,
) -> str:
    if include_text and tool_text:
        return (
            f"The assistant proposed this text for a pending action:\n{tool_text}\n\n"
            f"Revise it with this instruction:\n{instruction}"
        )
    return instruction


@log
def queue_tool_confirmation(
    *,
    tool_name: str,
    text_content: str,
    payload: dict[str, Any],
    channel_id: str,
    thread_ts: str | None,
    requester_user_id: str,
) -> str:
    spec = get_tool_confirmation_spec(tool_name)
    if not spec:
        return f"Error: unknown tool {tool_name!r} for confirmation."
    if not spec.requires_confirmation:
        return "Error: this tool does not use confirmation."
    recipient = (requester_user_id or "").strip()
    if not recipient:
        return (
            "Error: requester_user_id is required to show confirmation."
        )
    try:
        blocks = _build_confirmation_blocks(tool_name, spec, text_content, payload)
    except ValueError as e:
        return f"Error: {e}"
    slack_api.send_ephemeral_blocks(
        channel_id,
        thread_ts,
        recipient,
        spec.ephemeral_notification_text,
        blocks,
    )
    return "Queued for confirmation"


@log
def handle_confirm_action(body: dict) -> str:
    raw = (body.get("actions") or [{}])[0].get("value") or ""
    try:
        meta = json.loads(raw)
    except json.JSONDecodeError:
        return "Could not process this confirmation."
    if meta.get("v") != 1:
        return "Could not process this confirmation."
    tool_name = str(meta.get("tool_name") or "")
    spec = get_tool_confirmation_spec(tool_name)
    if not spec:
        return "Unknown tool."
    blocks = body.get("message", {}).get("blocks") or []
    try:
        text = parse_text_from_confirmation_blocks(blocks, spec.text_param_key)
    except _ConfirmationParseError as e:
        return str(e)
    payload = meta.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    return _execute_confirmed_tool(tool_name, text, payload)


def _execute_confirmed_tool(tool_name: str, text: str, payload: dict[str, Any]) -> str:
    tool = get_copilot_tool(tool_name)
    if not tool or not tool.execute_after_confirm:
        return f"Not implemented: {tool_name}"
    return tool.execute_after_confirm(text, payload)


@log
def handle_revise_open_modal(body: dict, client) -> None:
    try:
        action = (body.get("actions") or [{}])[0]
        meta = _parse_revise_metadata(action.get("value") or "")
        tool_name = str(meta.get("tool_name") or "")
        spec = get_tool_confirmation_spec(tool_name)
        if not spec:
            raise ValueError("Unknown tool.")
        blocks = body.get("message", {}).get("blocks") or []
        tool_text = parse_text_from_confirmation_blocks(blocks, spec.text_param_key)
        view = _build_tool_revise_modal_view(
            tool_text,
            json.dumps(meta, separators=(",", ":")),
        )
        client.views_open(trigger_id=body["trigger_id"], view=view)
    except _ConfirmationParseError as e:
        _reply_ephemeral_from_action(body, str(e))
    except ValueError as e:
        _reply_ephemeral_from_action(body, str(e))
    except Exception:
        _reply_ephemeral_from_action(
            body, "Could not open revise dialog. Try again."
        )


def register_tool_confirmation_handlers(app: App) -> None:
    @app.action(ACTION_TOOL_CONFIRM)
    def _on_confirm(ack, body, _client):
        ack()
        result = handle_confirm_action(body)
        _reply_ephemeral_from_action(body, result)

    @app.action(ACTION_TOOL_REVISE)
    def _on_revise(ack, body, client):
        ack()
        handle_revise_open_modal(body, client)

    @app.view(CALLBACK_TOOL_CONFIRM_REVISE_MODAL)
    def _on_modal_submit(ack, body, _client):
        view = body.get("view") or {}
        meta_raw = view.get("private_metadata") or ""
        user_id = body.get("user", {}).get("id") or ""
        try:
            outer = json.loads(meta_raw)
        except json.JSONDecodeError:
            ack(
                response_action="errors",
                errors={BLOCK_REVISE_INPUT: "Invalid dialog state."},
            )
            return
        tool_name = str(outer.get("tool_name") or "")
        spec = get_tool_confirmation_spec(tool_name)
        if not spec:
            ack(
                response_action="errors",
                errors={BLOCK_REVISE_INPUT: "Unknown tool."},
            )
            return
        channel_id = str(outer.get("payload", {}).get("channel_id") or "")
        thread_ts = outer.get("payload", {}).get("thread_ts")
        prepare_uid = str(outer.get("payload", {}).get("prepare_user_id") or "")
        if not channel_id or not prepare_uid:
            ack(
                response_action="errors",
                errors={
                    BLOCK_REVISE_INPUT: "Missing Slack context to restart.",
                },
            )
            return
        values = view.get("state", {}).get("values", {})
        block = values.get(BLOCK_REVISE_INPUT) or {}
        el = block.get(ACTION_REVISE_TEXT) or {}
        instruction = (el.get("value") or "").strip()
        if not instruction:
            ack(
                response_action="errors",
                errors={
                    BLOCK_REVISE_INPUT: "Enter an instruction or cancel.",
                },
            )
            return
        ack()

        include_text = _checkbox_include_text_selected(values)
        tool_text = str(outer.get("tool_text") or "")
        user_text = _compose_tool_revise_user_text(
            instruction, tool_text, include_text,
        )
        channel_name = slack_api.get_channel_prefixed_name(channel_id)
        from common.slack.slack_bot.react_runner import run_react_and_confirm

        run_react_and_confirm(
            channel_id,
            thread_ts or "",
            user_id,
            prepare_uid,
            user_text,
            context_kind="thread",
            channel_name=channel_name,
            copilot_trigger="tool_confirm_revise",
            copilot_action="confirmation_required_tool",
        )
