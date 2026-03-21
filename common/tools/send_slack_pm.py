import json

from common.slack.slack_api import slack_api
from common.slack.slack_bot.dm_confirmation import suggest_sending_dm
from common.tools.draft_context import get_invocation

SEND_SLACK_PM_TOOL = {
    "type": "function",
    "function": {
        "name": "send_slack_pm",
        "description": (
            "Queue a direct message to a workspace member. "
            "The config owner must confirm before anything is sent."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "user": {
                    "type": "string",
                    "description": "Display name, username, or Slack user id (U… / W…)",
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


def handle_send_slack_pm_call(arguments_json: str) -> str:
    try:
        args = json.loads(arguments_json or "{}")
        user, message = _require_str(args, "user"), _require_str(args, "message")
        uid = _resolve_target_user(user)
        inv = _require_invocation_context()
    except _ValidationError as e:
        return json.dumps({"error": str(e)})

    label = slack_api.get_user_display_name(uid) or user
    result = suggest_sending_dm(
        target_user_id=uid,
        message=message,
        channel_id=inv["channel_id"],
        thread_ts=inv.get("thread_ts"),
        target_label=label,
    )
    if result.startswith("Error:"):
        return json.dumps({"error": result})
    return json.dumps({"status": "queued", "detail": result})


def _resolve_target_user(user: str) -> str:
    uid = slack_api.resolve_user(user)
    if not uid:
        raise _ValidationError(f"Could not resolve user {user!r}")
    return uid


def _require_invocation_context() -> dict:
    inv = get_invocation()
    if not inv:
        raise _ValidationError("Missing invocation context for DM confirmation")
    return inv
