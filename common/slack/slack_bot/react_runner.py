"""Run the copilot ReAct loop and send the reply confirmation ephemeral."""

from __future__ import annotations

import logging
from collections.abc import Callable

from common.log import log
from common.slack.copilot_pipeline import (
    ThreadFetchError,
    fetch_channel_tail_messages,
    fetch_thread_messages,
    run_react_loop,
)
from common.slack.slack_api import slack_api
from common.slack.slack_bot.thread_reply_confirmation import ReviseError

_logger = logging.getLogger(__name__)

CHANNEL_INVITE_EPHEMERAL = "Add me to this channel first. /invite @CoPilot"
NO_ACTION_TEXT = "No action taken."


def _format_failure_message(
    copilot_trigger: str | None, copilot_action: str | None,
) -> str:
    parts = [p for p in (copilot_trigger, copilot_action) if p and str(p).strip()]
    if not parts:
        return "Failed to process request."
    return f"Failed to process: {', '.join(parts)}."


def _resolve_thread_messages(
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
        raise ReviseError("Missing thread anchor for revise.")
    return fetch_thread_messages(channel_id, anchor)


@log
def run_react_and_confirm(
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
        resolved_messages = _resolve_thread_messages(
            channel_id,
            thread_ts,
            context_kind,
            thread_messages,
        )
        reply_text = run_react_loop(
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
    except ReviseError as e:
        slack_api.send_ephemeral(
            channel_id,
            thread_ts,
            recipient_user_id,
            str(e),
        )
        return
    except Exception:
        _logger.exception("run_react_and_confirm failed")
        slack_api.send_ephemeral(
            channel_id,
            thread_ts,
            recipient_user_id,
            _format_failure_message(copilot_trigger, copilot_action),
        )
        return

    if not (reply_text or "").strip():
        reply_text = NO_ACTION_TEXT
    from common.slack.slack_bot.thread_reply_confirmation import (
        send_reply_confirmation,
    )

    send_reply_confirmation(
        channel_id,
        thread_ts,
        recipient_user_id,
        prepare_user_id,
        reply_text,
        context_kind=context_kind,
    )
