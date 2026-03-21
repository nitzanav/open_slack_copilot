"""Shared Slack thread text for LLM prompts (channel header, user roster, messages, reactions)."""

from __future__ import annotations

from datetime import datetime, timezone

from common.slack.slack_api import slack_api


def _mention(uid: str) -> str:
    if not uid:
        return "<@unknown>"
    return f"<@{uid}>"


def _ts_to_utc_label(ts: str) -> str:
    """Slack message ts -> [YYYY-MM-DD HH:MM] in UTC."""
    if not ts:
        return "-"
    try:
        sec = float(str(ts).split(".")[0])
        dt = datetime.fromtimestamp(sec, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, OSError):
        return str(ts)


def _reaction_lines(msg: dict) -> list[str]:
    out: list[str] = []
    for r in msg.get("reactions") or []:
        if not isinstance(r, dict):
            continue
        name = (r.get("name") or "").strip()
        if not name:
            continue
        users = r.get("users")
        if isinstance(users, list) and users:
            by = ", ".join(_mention(str(u)) for u in users)
        else:
            try:
                n = int(r.get("count") or 0)
            except (TypeError, ValueError):
                n = 0
            by = f"{n} user(s)" if n else "unknown users"
        out.append(f"  reaction :{name}: by {by}")
    return out


def format_slack_thread_for_prompt(
    messages: list[dict],
    *,
    channel_id: str,
    thread_ts: str,
    channel_display_name: str | None = None,
) -> str:
    """
    Format a Slack thread (API message dicts) for LLM consumption.

    Matches the shape used for RAG context: header, Users roster, then one block per
    message with optional per-reaction lines.
    """
    name = (
        channel_display_name
        if channel_display_name is not None
        else slack_api.get_channel_prefixed_name(channel_id)
    )

    order: list[str] = []
    seen: set[str] = set()
    for m in messages:
        uid = (m.get("user") or "").strip()
        if not uid:
            continue
        if uid not in seen:
            seen.add(uid)
            order.append(uid)

    lines = [
        f"Channel id: {channel_id}",
        f"Channel name: {name}",
        f"Thread id: {thread_ts}",
        "Users:",
    ]
    for uid in order:
        label = slack_api.get_user_display_name(uid) or uid
        lines.append(f"  {_mention(uid)}: {label}")
    lines.append("")

    for m in messages:
        uid = (m.get("user") or "unknown").strip() or "unknown"
        ts_label = _ts_to_utc_label(str(m.get("ts") or ""))
        body = (m.get("text") or "").strip()
        lines.append(f"[{ts_label}] {_mention(uid)}: {body}")
        lines.extend(_reaction_lines(m))
    return "\n".join(lines)


def format_rag_hits_for_prompt(
    channel_id: str,
    thread_ts: str,
    results: list[dict],
    *,
    channel_display_name: str | None = None,
) -> str:
    """
    Format RAG hit payloads (from, from_name, ts, text) using the same layout as
    `format_slack_thread_for_prompt`, without reactions.
    """
    name = (
        channel_display_name
        if channel_display_name is not None
        else slack_api.get_channel_prefixed_name(channel_id)
    )

    order: list[str] = []
    labels: dict[str, str] = {}
    for r in results:
        uid = (r.get("from") or "").strip()
        if not uid:
            continue
        if uid not in labels:
            order.append(uid)
            fn = (r.get("from_name") or "").strip()
            labels[uid] = fn or slack_api.get_user_display_name(uid) or uid

    lines = [
        f"Channel id: {channel_id}",
        f"Channel name: {name}",
        f"Thread id: {thread_ts}",
        "Users:",
    ]
    for uid in order:
        lines.append(f"  {_mention(uid)}: {labels[uid]}")
    lines.append("")

    for r in results:
        uid = (r.get("from") or "unknown").strip() or "unknown"
        ts_label = _ts_to_utc_label(str(r.get("ts") or ""))
        body = (r.get("text") or "").strip()
        lines.append(f"[{ts_label}] {_mention(uid)}: {body}")
    return "\n".join(lines)
