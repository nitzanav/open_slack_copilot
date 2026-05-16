import json

from common.slack.slack_directory_rag import slack_directory_rag
from common.tools.copilot_tool import CopilotTool, register_copilot_tool

LIST_USERS_TOOL = {
    "type": "function",
    "function": {
        "name": "list_users",
        "description": (
            "Resolve people in the Slack workspace from a free-text query "
            "(display name, real name, handle, or email). Returns matching "
            "users with their Slack user id (U…). "
            "Use this whenever you need a user id for an individual person. "
            "Do NOT pass user ids (U…) to `list_usergroup_members` — that "
            "tool is for user groups (subteams) only."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Name, handle, or email to search for.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Maximum matches to return (default 5).",
                },
            },
            "required": ["query"],
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


def handle_list_users_call(arguments_json: str) -> str:
    try:
        args = json.loads(arguments_json or "{}")
        query = _require_str(args, "query")
        top_k = max(1, min(50, int(args.get("top_k") or 5)))
        slack_directory_rag.build_if_missing()
        hits = slack_directory_rag.search(query, kind="user", top_k=top_k)
        users = [
            {
                "id": h.get("id"),
                "name": h.get("name"),
                "handle": h.get("handle"),
                "email": h.get("email"),
                "title": h.get("title"),
            }
            for h in hits
            if h.get("id")
        ]
        return json.dumps({"query": query, "users": users})
    except _ValidationError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": str(e)})


LIST_USERS = CopilotTool(
    name="list_users",
    llm_schema=LIST_USERS_TOOL,
    handle=handle_list_users_call,
    action_receipt_label="User search",
)

register_copilot_tool(LIST_USERS)
