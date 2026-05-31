"""Yield thread root ``ts`` from paginated ``conversations.history``."""

from __future__ import annotations

from typing import Iterator

from common.slack.slack_api import slack_api


def _slack_oldest_ts(oldest: float) -> str:
    """Format a Unix timestamp for Slack ``conversations.history`` ``oldest``."""
    return f"{oldest:.6f}"


def iter_recent_thread_ids(channel_id: str, oldest: float) -> Iterator[str]:
    """Yield each channel-history ``ts`` (thread root) with ts >= ``oldest``."""
    oldest_param = _slack_oldest_ts(oldest)
    cursor: str | None = None
    while True:
        kwargs: dict = {"channel": channel_id, "oldest": oldest_param, "limit": 200}
        if cursor:
            kwargs["cursor"] = cursor
        res = slack_api.get_client().conversations_history(**kwargs)
        yield from (m["ts"] for m in res.get("messages") or [])
        cursor = (res.get("response_metadata") or {}).get("next_cursor") or None
        if not cursor:
            return
