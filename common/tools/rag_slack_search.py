"""LLM tool: search Slack channel RAG indexes for relevant messages."""

import json

from common.slack import copilot_user_notify
from common.slack.slack_rag import slack_rag
from common.tools.copilot_tool import CopilotTool, register_copilot_tool
from common.tools.react_context import get_invocation
from config.config import settings, parse_duration_seconds

RAG_SLACK_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "rag_slack_search",
        "description": (
            "Search across Slack channel RAG indexes for messages relevant to a "
            "free-text query. By default searches the configured cross-channel "
            "set; pass `channel_ids` to override. Builds missing indexes on "
            "demand (may take time on first use)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Free-text query to semantically search Slack messages.",
                },
                "channel_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional Slack channel ids to search. Defaults to the "
                        "configured cross-channel set."
                    ),
                },
                "top_k": {
                    "type": "integer",
                    "description": "Maximum matches to return (default 10).",
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


def _resolve_channel_ids(args: dict) -> list[str]:
    raw = args.get("channel_ids")
    if isinstance(raw, list):
        ids = [str(c).strip() for c in raw if str(c).strip()]
        if ids:
            return ids
    return list(settings.rag.cross_channel)


def _build_indication_callback():
    inv = get_invocation()
    if not inv:
        return None
    channel_id = inv.get("channel_id")
    thread_ts = inv.get("thread_ts")
    user_id = inv.get("user_id")
    if not (channel_id and user_id):
        return None
    def notify(text: str) -> None:
        copilot_user_notify.notify_progress(channel_id, thread_ts, user_id, text)
    return notify


def _checkpoint_seconds() -> float:
    return parse_duration_seconds(settings.rag.checkpoint_duration)


def handle_rag_slack_search_call(arguments_json: str) -> str:
    try:
        args = json.loads(arguments_json or "{}")
        query = _require_str(args, "query")
        top_k = max(1, min(50, int(args.get("top_k") or 10)))
        channel_ids = _resolve_channel_ids(args)
        if not channel_ids:
            return json.dumps({"error": "no channel_ids provided and no default cross-channel set configured"})
        inv = get_invocation() or {}
        exclude_channel = inv.get("channel_id")
        hits = slack_rag.ensure_built_and_query_cross_channel(
            channel_ids, query,
            exclude_channel=exclude_channel,
            top_k=top_k,
            checkpoint_seconds=_checkpoint_seconds(),
            indication_callback=_build_indication_callback(),
        )
        results = [
            {
                "channel": h.get("channel"),
                "ts": h.get("ts"),
                "text": h.get("text"),
                "from": h.get("from"),
                "from_name": h.get("from_name"),
            }
            for h in hits
        ]
        return json.dumps({
            "query": query,
            "channels": channel_ids,
            "results": results,
        })
    except _ValidationError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": str(e)})


RAG_SLACK_SEARCH = CopilotTool(
    name="rag_slack_search",
    llm_schema=RAG_SLACK_SEARCH_TOOL,
    handle=handle_rag_slack_search_call,
    action_receipt_label="Slack RAG search",
)

register_copilot_tool(RAG_SLACK_SEARCH)
