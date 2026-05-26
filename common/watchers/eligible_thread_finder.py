"""Yield distinct ``thread_ts`` from paginated ``conversations.history``."""

from __future__ import annotations

from typing import Iterator

from common.slack.slack_api import slack_api


def iter_recent_thread_ids(channel_id: str, oldest: float) -> Iterator[str]:
    """Yield each distinct ``thread_ts`` (root ``ts >= oldest``), in channel-history order."""
    seen: set[str] = set()
    cursor: str | None = None
    while True:
        res = _fetch_history_page(channel_id, oldest, cursor)
        for msg in res.get("messages") or []:
            tts = _thread_ts_of(msg)
            if tts and tts not in seen:
                seen.add(tts)
                yield tts
        cursor = (res.get("response_metadata") or {}).get("next_cursor") or None
        if not cursor:
            return


def _fetch_history_page(channel_id: str, oldest: float, cursor: str | None) -> dict:
    kwargs: dict = {"channel": channel_id, "oldest": str(oldest), "limit": 200}
    if cursor:
        kwargs["cursor"] = cursor
    return slack_api.get_client().conversations_history(**kwargs)


def _thread_ts_of(msg: dict) -> str:
    return (msg.get("thread_ts") or msg.get("ts") or "").strip()
