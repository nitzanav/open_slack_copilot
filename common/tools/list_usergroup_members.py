import json

from slack_sdk.errors import SlackApiError

from common.slack.slack_api import slack_api
from common.tools.copilot_tool import CopilotTool, register_copilot_tool

LIST_USERGROUP_MEMBERS_TOOL = {
    "type": "function",
    "function": {
        "name": "list_usergroup_members",
        "description": (
            "List Slack user IDs in a User Group (subteam). "
            "Pass the group id (S…), a subteam mention from a message "
            "(e.g. <!subteam^S…|label>), handle (e.g. backend-team), or @handle. "
            "Requires the Slack app to have usergroups:read."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "usergroup": {
                    "type": "string",
                    "description": (
                        "User group id (S…), <!subteam^S…> snippet, or handle/name"
                    ),
                },
            },
            "required": ["usergroup"],
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


def handle_list_usergroup_members_call(arguments_json: str) -> str:
    try:
        args = json.loads(arguments_json or "{}")
        query = _require_str(args, "usergroup")
        ugid, user_ids = slack_api.list_usergroup_members(query)
        return json.dumps({
            "usergroup_id": ugid,
            "user_ids": user_ids,
        })
    except _ValidationError as e:
        return json.dumps({"error": str(e)})
    except ValueError as e:
        return json.dumps({"error": str(e)})
    except SlackApiError as e:
        resp = getattr(e, "response", None) or {}
        err = resp.get("error") if isinstance(resp, dict) else None
        return json.dumps({"error": err or str(e)})


LIST_USERGROUP_MEMBERS = CopilotTool(
    name="list_usergroup_members",
    llm_schema=LIST_USERGROUP_MEMBERS_TOOL,
    handle=handle_list_usergroup_members_call,
)

register_copilot_tool(LIST_USERGROUP_MEMBERS)
