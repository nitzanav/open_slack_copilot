"""User confirmation for tools that require it (Slack Block Kit ephemerals).

A ``skill_runs`` row is keyed by ``<thread_ts>__<action_ts>`` and holds the tool
name, payload, draft text, and optional ``conversation_id``. Slack button values
carry ``conversation_id`` (``<skill_name>__<thread_ts>__<action_ts>``) when the
copilot run created a persisted conversation; otherwise the legacy row key only.
"""

from __future__ import annotations

import json
from typing import Any

from slack_bolt import App

from common.conversations import conversations
from common.log import log
from common.skill_runs import skill_runs
from common.skill_thumbs_up import skill_thumbs_up
from common.slack import copilot_user_notify
from common.slack.slack_api import slack_api
from common.tools.copilot_tool import (
    ToolConfirmationSpec,
    get_copilot_tool,
    get_tool_confirmation_spec,
)
from common.tools.react_context import get_invocation
from config.config import settings

_SLACK_BOT_CONFIG = settings.slack_bot
_PLAIN_CHUNK = _SLACK_BOT_CONFIG.get("block_kit_plain_text_chunk", 3000)
_MAX_BODY_BLOCKS = _SLACK_BOT_CONFIG.get("block_kit_max_body_blocks", 48)
_BUTTON_VALUE_LIMIT = _SLACK_BOT_CONFIG.get("button_value_limit", 2000)

BLOCK_HEADER = "tool_confirm_header"
BLOCK_BODY_PREFIX = "tool_confirm_body_"
BLOCK_ACTIONS = "tool_confirm_actions"
ACTION_TOOL_CONFIRM = "tool_confirm_action"
ACTION_TOOL_REVISE = "tool_confirm_revise"
ACTION_TOOL_THUMBS_UP = "tool_confirm_thumbs_up"
CALLBACK_TOOL_CONFIRM_REVISE_MODAL = "tool_confirm_revise_modal"
BLOCK_REVISE_INPUT = "tool_confirm_revise_input"
ACTION_REVISE_TEXT = "tool_confirm_revise_text"


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
            "text": {"type": "mrkdwn", "text": chunk},
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
    button_value: str,
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
        _actions_block(spec, button_value),
    ]


def _actions_block(spec: ToolConfirmationSpec, button_value: str) -> dict:
    if len(button_value) > _BUTTON_VALUE_LIMIT:
        raise ValueError("Confirmation button value too long for Slack.")
    return {
        "type": "actions",
        "block_id": BLOCK_ACTIONS,
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Revise"},
                "action_id": ACTION_TOOL_REVISE,
                "value": button_value,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": spec.confirm_button_text},
                "style": "primary",
                "action_id": ACTION_TOOL_CONFIRM,
                "value": button_value,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "\U0001f44d", "emoji": True},
                "action_id": ACTION_TOOL_THUMBS_UP,
                "value": button_value,
                "accessibility_label": "This was helpful",
            },
        ],
    }


def _row_key_from_actions(body: dict) -> str:
    return (body.get("actions") or [{}])[0].get("value") or ""


def _skill_run_row_from_interactive_key(interactive_key: str) -> dict[str, Any] | None:
    """Resolve a Slack button value to its skill_runs row.

    The button value is a ``conversation_id`` for new-style flows, or a legacy
    ``skill_runs`` row key. Conversation ids are opaque: we never parse them
    and instead fetch the conversation row to read ``thread_ts`` / ``action_ts``.
    """
    conv = conversations.get(interactive_key)
    if conv:
        return skill_runs.get(skill_runs._row_key(conv.thread_ts, conv.action_ts))
    return skill_runs.get(interactive_key)


def _ephemeral_thread_ts(body: dict) -> str | None:
    msg = body.get("message") or {}
    container = body.get("container") or {}
    return msg.get("thread_ts") or container.get("thread_ts") or msg.get("ts")


def _reply_ephemeral_from_action(body: dict, text: str) -> None:
    channel_id = body["channel"]["id"]
    user_id = body["user"]["id"]
    thread_ts = _ephemeral_thread_ts(body)
    copilot_user_notify.notify_user_text(channel_id, thread_ts, user_id, text)


def _build_tool_revise_modal_view(private_metadata: str) -> dict[str, Any]:
    return {
        "type": "modal",
        "callback_id": CALLBACK_TOOL_CONFIRM_REVISE_MODAL,
        "private_metadata": private_metadata,
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
        ],
    }


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
        return "Error: requester_user_id is required to show confirmation."

    inv = get_invocation() or {}
    action_ts = (inv.get("action_ts") or "").strip()
    if not action_ts:
        return "Error: missing action_ts in invocation context."
    skill_id = inv.get("skill_id")
    conversation_id = (inv.get("conversation_id") or "").strip() or None
    button_value = skill_runs.init_run(
        skill_id=skill_id,
        channel_id=channel_id,
        thread_ts=thread_ts or "",
        action_ts=action_ts,
        requester_user_id=recipient,
        tool_name=tool_name,
        payload=payload,
        text=text_content,
        conversation_id=conversation_id,
    )
    try:
        blocks = _build_confirmation_blocks(
            tool_name, spec, text_content, payload, button_value,
        )
    except ValueError as e:
        return f"Error: {e}"
    copilot_user_notify.notify_confirmation_blocks(
        channel_id,
        thread_ts,
        recipient,
        spec.ephemeral_notification_text,
        blocks,
    )
    return "Tool confirmation requested"


@log
def handle_confirm_action(body: dict) -> str:
    interactive_key = _row_key_from_actions(body)
    if not interactive_key:
        return "Could not process this confirmation."
    row = _skill_run_row_from_interactive_key(interactive_key)
    if not row:
        return "This confirmation has expired."
    tool_name = str(row.get("tool_name") or "")
    spec = get_tool_confirmation_spec(tool_name)
    if not spec:
        return "Unknown tool."
    text = str(row.get("text") or "")
    payload = row.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    result = _execute_confirmed_tool(tool_name, text, payload)
    conv = conversations.get(interactive_key)
    if conv:
        cid = conv.id or interactive_key
        summary = (result or "").strip()[:3800]
        conversations.append_message(
            cid,
            "assistant",
            f"The user confirmed the pending action. Result: {summary}".strip(),
        )
        conversations.mark_waiting_for_confirmation(cid, False)
        fresh = conversations.get(cid)
        if fresh:
            completed = fresh.current_or_first_step
            nxt = fresh.next_step_after(completed)
            if nxt is None:
                conversations.mark_end(cid)
            else:
                conversations.set_current_step(cid, nxt)
        from common.slack.conversations_driver import continue_with_invocation_context

        latest = conversations.get(cid)
        if latest and not latest.is_end:
            continue_with_invocation_context(
                cid,
                tools=None,
                excluded_tools=None,
                tool_dispatch=None,
                on_agent_event=None,
                skip_next_step_intro=False,
            )
    return result


def _execute_confirmed_tool(tool_name: str, text: str, payload: dict[str, Any]) -> str:
    tool = get_copilot_tool(tool_name)
    if not tool or not tool.execute_after_confirm:
        return f"Not implemented: {tool_name}"
    return tool.execute_after_confirm(text, payload)


@log
def handle_revise_open_modal(body: dict, client) -> None:
    try:
        interactive_key = _row_key_from_actions(body)
        if not interactive_key:
            raise ValueError("Missing confirmation context.")
        row = _skill_run_row_from_interactive_key(interactive_key)
        if not row:
            raise ValueError("This confirmation has expired.")
        tool_name = str(row.get("tool_name") or "")
        spec = get_tool_confirmation_spec(tool_name)
        if not spec:
            raise ValueError("Unknown tool.")
        view = _build_tool_revise_modal_view(interactive_key)
        client.views_open(trigger_id=body["trigger_id"], view=view)
    except ValueError as e:
        _reply_ephemeral_from_action(body, str(e))
    except Exception:
        _reply_ephemeral_from_action(
            body, "Could not open revise dialog. Try again.",
        )


@log
def handle_thumbs_up(body: dict) -> str:
    interactive_key = _row_key_from_actions(body)
    if not interactive_key:
        return "Could not process this thumbs-up."
    row = _skill_run_row_from_interactive_key(interactive_key)
    if not row:
        return "This confirmation has expired; cannot record thumbs-up."
    skill_id = row.get("skill_id")
    thread_ts = str(row.get("thread_ts") or "")
    action_ts = str(row.get("action_ts") or "")
    if not (isinstance(skill_id, str) and skill_id.strip() and thread_ts and action_ts):
        return "Missing skill context; thumbs-up not saved."
    ok = skill_thumbs_up.add_reference(skill_id, thread_ts, action_ts)
    if not ok:
        return "Could not save thumbs-up for this skill."
    return f"Thanks — saved as an example for `{skill_id}`."


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

    @app.action(ACTION_TOOL_THUMBS_UP)
    def _on_thumbs_up(ack, body, _client):
        ack()
        result = handle_thumbs_up(body)
        _reply_ephemeral_from_action(body, result)

    @app.view(CALLBACK_TOOL_CONFIRM_REVISE_MODAL)
    def _on_modal_submit(ack, body, _client):
        view = body.get("view") or {}
        interactive_key = (view.get("private_metadata") or "").strip()
        user_id = body.get("user", {}).get("id") or ""
        row = _skill_run_row_from_interactive_key(interactive_key) if interactive_key else None
        if not row:
            ack(
                response_action="errors",
                errors={BLOCK_REVISE_INPUT: "Invalid dialog state."},
            )
            return
        tool_name = str(row.get("tool_name") or "")
        spec = get_tool_confirmation_spec(tool_name)
        if not spec:
            ack(
                response_action="errors",
                errors={BLOCK_REVISE_INPUT: "Unknown tool."},
            )
            return
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        channel_id = str(payload.get("channel_id") or row.get("channel_id") or "")
        thread_ts = payload.get("thread_ts") or row.get("thread_ts")
        prepare_uid = str(payload.get("prepare_user_id") or "")
        if not channel_id or not prepare_uid:
            ack(
                response_action="errors",
                errors={BLOCK_REVISE_INPUT: "Missing Slack context to restart."},
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
        conv = conversations.get(interactive_key) if interactive_key else None
        if conv:
            ack()
            cid = conv.id or interactive_key
            conversations.mark_waiting_for_confirmation(cid, False)
            conversations.append_message(cid, "user", instruction)
            from common.slack.conversations_driver import continue_with_invocation_context

            continue_with_invocation_context(
                cid,
                tools=None,
                excluded_tools=None,
                tool_dispatch=None,
                on_agent_event=None,
                skip_next_step_intro=True,
            )
            return

        ack()
        channel_name = slack_api.get_channel_prefixed_name(channel_id)
        from common.slack.slack_bot.react_runner import run_react_and_confirm

        ctx_kind = str(payload.get("context_kind") or "thread")
        run_react_and_confirm(
            channel_id,
            thread_ts or "",
            user_id,
            prepare_uid,
            instruction,
            context_kind=ctx_kind,
            channel_name=channel_name,
            copilot_trigger="tool_confirm_revise",
            copilot_action="confirmation_required_tool",
        )
