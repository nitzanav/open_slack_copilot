"""User-visible Slack ephemerals for the copilot (progress, errors, ReAct outcomes).

Call sites use these helpers; ``slack_api`` performs ``chat.postEphemeral``.
"""

from __future__ import annotations

from common.slack.slack_api import slack_api


def notify_progress(
    channel_id: str, thread_ts: str | None, user_id: str, text: str,
) -> None:
    """Non-fatal status while work is in flight (e.g. RAG indexing)."""
    slack_api.send_ephemeral(channel_id, thread_ts, user_id, text)


def notify_error(
    channel_id: str, thread_ts: str | None, user_id: str, text: str,
) -> None:
    """Failures, invalid context, or missing access the user must fix."""
    slack_api.send_ephemeral(channel_id, thread_ts, user_id, text)


def notify_react_feedback(
    channel_id: str, thread_ts: str | None, user_id: str, text: str,
) -> None:
    """Outcome of the ReAct loop visible only to the invoker (tool errors, no-submit hints)."""
    slack_api.send_ephemeral(channel_id, thread_ts, user_id, text)


def notify_user_text(
    channel_id: str, thread_ts: str | None, user_id: str, text: str,
) -> None:
    """Plain ephemeral text for interactive flows (confirm/revise, parsing errors)."""
    slack_api.send_ephemeral(channel_id, thread_ts, user_id, text)


def notify_confirmation_blocks(
    channel_id: str,
    thread_ts: str | None,
    user_id: str,
    fallback_text: str,
    blocks: list[dict],
) -> None:
    """Block Kit confirmation UI, user-only."""
    slack_api.send_ephemeral_blocks(
        channel_id, thread_ts, user_id, fallback_text, blocks,
    )
