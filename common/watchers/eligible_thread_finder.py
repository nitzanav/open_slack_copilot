"""Yield thread root ``ts`` from paginated ``conversations.history``."""

from __future__ import annotations

from typing import Iterator

from common.slack.slack_api import slack_api


def _slack_oldest_ts(oldest: float) -> str:
    """Format a Unix timestamp for Slack ``conversations.history`` ``oldest``."""
    return f"{oldest:.6f}"


def _thread_root_ts(message: dict) -> str:
    """Root ``thread_ts`` for a channel-history row (root post uses ``ts``)."""
    return (message.get("thread_ts") or message.get("ts") or "").strip()


def iter_recent_thread_ids(channel_id: str, oldest: float) -> Iterator[str]:
    """Yield distinct thread root ids from ``conversations.history`` (newest first)."""
    oldest_param = _slack_oldest_ts(oldest)
    seen: set[str] = set()
    cursor: str | None = None
    while True:
        kwargs: dict = {"channel": channel_id, "oldest": oldest_param, "limit": 200}
        if cursor:
            kwargs["cursor"] = cursor
        res = slack_api.get_client().conversations_history(**kwargs)
        for m in res.get("messages") or []:
            root = _thread_root_ts(m)
            if root and root not in seen:
                seen.add(root)
                yield root
        cursor = (res.get("response_metadata") or {}).get("next_cursor") or None
        if not cursor:
            return
