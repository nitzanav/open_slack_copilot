"""Run the copilot ReAct loop; thread reply is submitted via send_thread_reply tool confirmation."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from common.log import log
from common.llm.llm_client.llm_client import ToolCallRecord
from common.slack.copilot_pipeline import (
    ReactLoopResult,
    ThreadFetchError,
    fetch_channel_tail_messages,
    fetch_thread_messages,
    run_react_loop,
)
from common.slack.slack_api import slack_api
from common.tools.copilot_tool import TOOL_JSON_STATUS_CONFIRMATION_REQUESTED

_logger = logging.getLogger(__name__)

CHANNEL_INVITE_EPHEMERAL = "Add me to this channel first. /invite @CoPilot"
_NO_SUBMIT_MSG = (
    "The assistant did not call send_thread_reply with the message text. "
    "Try again or rephrase your instruction."
)


class ReviseError(Exception):
    """User-visible Revise flow error."""


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


def _trace_shows_send_thread_reply_confirmation_requested(
    trace: list[ToolCallRecord],
) -> bool:
    """True if send_thread_reply returned status tool_confirmation_requested (Slack UI was shown)."""
    for rec in reversed(trace):
        if (rec.name or "") != "send_thread_reply":
            continue
        prev = (rec.result_preview or "").strip()
        try:
            obj = json.loads(prev)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("status") == TOOL_JSON_STATUS_CONFIRMATION_REQUESTED:
            return True
    return False


def _format_tool_errors_ephemeral(tool_errors: list[str]) -> str:
    lines = "\n".join(f"• {line}" for line in tool_errors)
    return f"*Tool errors*\n{lines}"


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
        loop_out = run_react_loop(
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
            context_kind=context_kind,
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

    _post_loop_ephemeral(
        channel_id,
        thread_ts,
        recipient_user_id,
        loop_out,
    )


def _post_loop_ephemeral(
    channel_id: str,
    thread_ts: str,
    recipient_user_id: str,
    loop_out: ReactLoopResult,
) -> None:
    # send_thread_reply already opened Revise/Confirm; only surface other tool failures.
    thread_reply_confirmation_requested = _trace_shows_send_thread_reply_confirmation_requested(
        loop_out.tool_trace,
    )
    if thread_reply_confirmation_requested:
        if loop_out.tool_errors:
            slack_api.send_ephemeral(
                channel_id,
                thread_ts,
                recipient_user_id,
                _format_tool_errors_ephemeral(loop_out.tool_errors),
            )
        return

    # No successful send_thread_reply confirmation path: explain + optional errors + model text excerpt.
    ephemeral_sections: list[str] = [_NO_SUBMIT_MSG]
    if loop_out.tool_errors:
        ephemeral_sections.append(_format_tool_errors_ephemeral(loop_out.tool_errors))
    assistant = (loop_out.text or "").strip()
    if assistant:
        excerpt = assistant[:800] + ("…" if len(assistant) > 800 else "")
        ephemeral_sections.append(f"*Assistant text (not submitted):*\n{excerpt}")
    slack_api.send_ephemeral(
        channel_id,
        thread_ts,
        recipient_user_id,
        "\n\n".join(ephemeral_sections),
    )
