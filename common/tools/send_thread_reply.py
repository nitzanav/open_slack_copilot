import json
from typing import Any

from common.slack.slack_api import slack_api
from common.slack.slack_bot.tool_confirmation import queue_tool_confirmation
from common.tools.copilot_tool import (
    TOOL_JSON_STATUS_CONFIRMATION_REQUESTED,
    CopilotTool,
    ToolConfirmationSpec,
    register_copilot_tool,
)
from common.tools.react_context import get_invocation

_TOOL_NAME = "send_thread_reply"

SEND_THREAD_REPLY_TOOL = {
    "type": "function",
    "function": {
        "name": _TOOL_NAME,
        "description": (
            "Submit the proposed reply to this thread. The member who invoked the copilot "
            "must confirm in Slack before the message is posted."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Full reply text to post in the thread after confirmation",
                },
            },
            "required": ["message"],
        },
    },
}


class _ValidationError(Exception):
    pass


def _require_invocation_context() -> dict:
    inv = get_invocation()
    if not inv:
        raise _ValidationError("Missing invocation context for tool confirmation")
    return inv


def _require_str(args: dict, key: str) -> str:
    val = (args.get(key) or "").strip()
    if not val:
        raise _ValidationError(f"{key} is required")
    return val


def _invoke(arguments_json: str) -> str:
    try:
        args = json.loads(arguments_json or "{}")
        message = _require_str(args, "message")
        inv = _require_invocation_context()
    except _ValidationError as e:
        return json.dumps({"error": str(e)})

    thread_ts = (inv.get("thread_ts") or "").strip()
    channel_id = (inv.get("channel_id") or "").strip()
    if not thread_ts or not channel_id:
        return json.dumps({"error": "Missing channel or thread anchor for thread reply"})

    result = queue_tool_confirmation(
        tool_name=_TOOL_NAME,
        text_content=message,
        payload={
            "channel_id": channel_id,
            "thread_ts": thread_ts,
            "prepare_user_id": inv.get("user_id") or "",
            "context_kind": inv.get("context_kind") or "thread",
        },
        channel_id=channel_id,
        thread_ts=thread_ts,
        requester_user_id=inv.get("user_id") or "",
    )
    if result.startswith("Error:"):
        return json.dumps({"error": result})
    return json.dumps({"status": TOOL_JSON_STATUS_CONFIRMATION_REQUESTED, "detail": result})


def _execute_after_confirm(text: str, payload: dict[str, Any]) -> str:
    channel_id = (payload.get("channel_id") or "").strip()
    thread_ts = (payload.get("thread_ts") or "").strip()
    if not channel_id or not thread_ts:
        return "Missing channel or thread for this action."
    body = (text or "").strip()
    if not body:
        return "Nothing to post."
    try:
        slack_api.post_thread_message(channel_id, thread_ts, body)
    except Exception as e:
        return f"Failed to post: {e}"
    return "Posted to thread."


SEND_THREAD_REPLY = CopilotTool(
    name=_TOOL_NAME,
    llm_schema=SEND_THREAD_REPLY_TOOL,
    handle=_invoke,
    confirmation=ToolConfirmationSpec(
        text_param_key="message",
        ephemeral_notification_text="Confirm thread reply",
        confirmation_header_markdown=(
            "*Thread reply*\n"
            "This will be posted in the thread as the app after you confirm."
        ),
    ),
    execute_after_confirm=_execute_after_confirm,
)

register_copilot_tool(SEND_THREAD_REPLY)
