"""Single path: resolve thread context, prepare_draft, unified errors, Revise ephemeral."""

from __future__ import annotations

import logging
from collections.abc import Callable

from common.log import log
from common.slack.copilot_pipeline import (
    ThreadFetchError,
    fetch_channel_tail_messages,
    fetch_thread_messages,
    prepare_draft,
)
from common.slack.slack_api import slack_api

_logger = logging.getLogger(__name__)

CHANNEL_INVITE_EPHEMERAL = "Add me to this channel first. /invite @CoPilot"
NO_ACTION_DRAFT_TEXT = "No action taken."


class DraftReviseError(Exception):
    """User-visible Revise flow error."""


def format_prepare_failure_message(
    copilot_trigger: str | None, copilot_action: str | None,
) -> str:
    parts = [p for p in (copilot_trigger, copilot_action) if p and str(p).strip()]
    if not parts:
        return "Failed to process draft."
    return f"Failed to process: {', '.join(parts)}."


def _resolve_thread_messages_when_needed(
    channel_id: str,
    thread_ts: str,
    context_kind: str,
    thread_messages: list[dict] | None,
) -> list[dict]:
    if thread_messages is not None:
        return thread_messages
    kind = (context_kind or "thread").strip() or "thread"
    if kind == "channel_tail":
        return fetch_channel_tail_messages(channel_id)
    anchor = (thread_ts or "").strip()
    if not anchor:
        raise DraftReviseError("Missing thread anchor for revise.")
    return fetch_thread_messages(channel_id, anchor)


@log
def prepare_draft_and_send_ephemeral(
    channel_id: str,
    thread_ts: str,
    recipient_user_id: str,
    prepare_user_id: str,
    user_text: str,
    *,
    context_kind: str,
    channel_name: str | None = None,
    thread_messages: list[dict] | None = None,
    tools: list[dict] | None = None,
    excluded_tools: list[dict] | None = None,
    tool_dispatch: Callable[[str, str], str] | None = None,
    copilot_trigger: str | None = None,
    copilot_action: str | None = None,
) -> None:
    if not recipient_user_id:
        return
    try:
        resolved_messages = _resolve_thread_messages_when_needed(
            channel_id,
            thread_ts,
            context_kind,
            thread_messages,
        )
        draft = prepare_draft(
            channel_id,
            thread_ts,
            prepare_user_id,
            user_text,
            channel_name=channel_name,
            thread_messages=resolved_messages,
            tools=tools,
            excluded_tools=excluded_tools,
            tool_dispatch=tool_dispatch,
            copilot_trigger=copilot_trigger,
            copilot_action=copilot_action,
        )
    except ThreadFetchError:
        slack_api.send_ephemeral(
            channel_id,
            thread_ts,
            recipient_user_id,
            CHANNEL_INVITE_EPHEMERAL,
        )
        return
    except DraftReviseError as e:
        slack_api.send_ephemeral(
            channel_id,
            thread_ts,
            recipient_user_id,
            str(e),
        )
        return
    except Exception:
        _logger.exception("prepare_draft_and_send_ephemeral failed")
        slack_api.send_ephemeral(
            channel_id,
            thread_ts,
            recipient_user_id,
            format_prepare_failure_message(copilot_trigger, copilot_action),
        )
        return

    if not (draft or "").strip():
        draft = NO_ACTION_DRAFT_TEXT
    from common.slack.slack_bot.draft_revise_actions import (
        send_draft_ephemeral_with_revise,
    )

    send_draft_ephemeral_with_revise(
        channel_id,
        thread_ts,
        recipient_user_id,
        prepare_user_id,
        draft,
        context_kind=context_kind,
    )
