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

_TOOL_NAME = "send_slack_pm"

SEND_SLACK_PM_TOOL = {
    "type": "function",
    "function": {
        "name": _TOOL_NAME,
        "description": (
            "Queue a direct message to a workspace member. "
            "The requesting user confirms the message in Slack before it is sent."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "user": {
                    "type": "string",
                    "description": "Slack user id (U…) from the thread context. Falls back to display name lookup.",
                },
                "message": {"type": "string", "description": "DM body"},
            },
            "required": ["user", "message"],
        },
    },
}


class _ValidationError(Exception):
    pass


def _require_str(args: dict, key: str) -> str:
    val = (args.get(key) or "").strip()
    if not val:
        raise _ValidationError(f"{key} is required")
    return val


def _invoke(arguments_json: str) -> str:
    try:
        args = json.loads(arguments_json or "{}")
        user, message = _require_str(args, "user"), _require_str(args, "message")
        uid = _resolve_target_user(user)
        inv = _require_invocation_context()
    except _ValidationError as e:
        return json.dumps({"error": str(e)})

    result = queue_tool_confirmation(
        tool_name=_TOOL_NAME,
        text_content=message,
        payload={
            "target_user_id": uid,
            "channel_id": inv["channel_id"],
            "thread_ts": inv.get("thread_ts"),
            "prepare_user_id": inv.get("user_id") or "",
            "context_kind": inv.get("context_kind") or "thread",
        },
        channel_id=inv["channel_id"],
        thread_ts=inv.get("thread_ts"),
        requester_user_id=inv.get("user_id") or "",
    )
    if result.startswith("Error:"):
        return json.dumps({"error": result})
    return json.dumps({"status": TOOL_JSON_STATUS_CONFIRMATION_REQUESTED, "detail": result})


def _execute_after_confirm(text: str, payload: dict[str, Any]) -> str:
    uid = (payload.get("target_user_id") or "").strip()
    if not uid:
        return "Missing recipient for this action."
    try:
        slack_api.send_dm(uid, text)
    except Exception as e:
        return f"Failed to send: {e}"
    return "Sent."


SEND_SLACK_PM = CopilotTool(
    name=_TOOL_NAME,
    llm_schema=SEND_SLACK_PM_TOOL,
    handle=_invoke,
    confirmation=ToolConfirmationSpec(
        text_param_key="message",
        ephemeral_notification_text="Confirm pending action",
        confirmation_header_markdown=(
            "*Direct message*\n"
            "This will be sent as a private Slack message to the selected member."
        ),
    ),
    execute_after_confirm=_execute_after_confirm,
)

register_copilot_tool(SEND_SLACK_PM)


def _resolve_target_user(user: str) -> str:
    uid = slack_api.resolve_user(user)
    if not uid:
        raise _ValidationError(f"Could not resolve user {user!r}")
    return uid


def _require_invocation_context() -> dict:
    inv = get_invocation()
    if not inv:
        raise _ValidationError("Missing invocation context for tool confirmation")
    return inv
