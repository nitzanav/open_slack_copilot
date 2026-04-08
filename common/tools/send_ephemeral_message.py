import json

from common.slack.slack_api import slack_api
from common.tools.copilot_tool import CopilotTool, register_copilot_tool
from common.tools.react_context import get_invocation

_TOOL_NAME = "send_ephemeral_message"

SEND_EPHEMERAL_MESSAGE_TOOL = {
    "type": "function",
    "function": {
        "name": _TOOL_NAME,
        "description": (
            "Post a Slack ephemeral message in the current thread/channel context. "
            "Only the chosen user sees it (not a DM). Use for reminders and nudges."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "user": {
                    "type": "string",
                    "description": "Slack user id (U…) from the thread context. Falls back to display name lookup.",
                },
                "message": {
                    "type": "string",
                    "description": "Ephemeral text (brief; may include thread links).",
                },
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

    channel_id = inv["channel_id"]
    thread_ts = inv.get("thread_ts") or None
    if thread_ts == "":
        thread_ts = None
    try:
        slack_api.send_ephemeral(channel_id, thread_ts, uid, message)
    except Exception as e:
        return json.dumps({"error": str(e)})
    return json.dumps({"status": "sent"})


SEND_EPHEMERAL_MESSAGE = CopilotTool(
    name=_TOOL_NAME,
    llm_schema=SEND_EPHEMERAL_MESSAGE_TOOL,
    handle=_invoke,
)

register_copilot_tool(SEND_EPHEMERAL_MESSAGE)


def _resolve_target_user(user: str) -> str:
    uid = slack_api.resolve_user(user)
    if not uid:
        raise _ValidationError(f"Could not resolve user {user!r}")
    return uid


def _require_invocation_context() -> dict:
    inv = get_invocation()
    if not inv:
        raise _ValidationError("Missing invocation context for ephemeral message")
    return inv
