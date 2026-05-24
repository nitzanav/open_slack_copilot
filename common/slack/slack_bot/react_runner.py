"""Run the copilot ReAct loop; thread reply is submitted via send_thread_reply_on_behalf_of_requester tool confirmation."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from common.log import log
from common.llm.llm_client.llm_client import AgentEvent, ToolCallRecord
from common.slack.copilot_pipeline import (
    ForcedSkillMissing,
    ReactLoopResult,
    ThreadFetchError,
    fetch_channel_tail_messages,
    fetch_thread_messages,
    run_react_loop,
)
from common.slack import copilot_user_notify
from common.tools.copilot_tool import (
    TOOL_JSON_STATUS_CONFIRMATION_REQUESTED,
    get_tool_confirmation_spec,
    tool_action_receipt_label,
)

_logger = logging.getLogger(__name__)

CHANNEL_INVITE_EPHEMERAL = "Add me to this channel first. /invite @CoPilot"
_EMPTY_RUN_MSG = "Failed to process request."
_NO_SUBMIT_MSG = (
    "The assistant did not call send_thread_reply_on_behalf_of_requester with the message text. "
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


def _trace_shows_confirm_ui_pending(trace: list[ToolCallRecord]) -> bool:
    """True if a confirm-mode tool returned tool_confirmation_requested (Slack UI was shown)."""
    for rec in reversed(trace):
        name = rec.name or ""
        if get_tool_confirmation_spec(name) is None:
            continue
        prev = (rec.result_preview or "").strip()
        try:
            obj = json.loads(prev)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("status") == TOOL_JSON_STATUS_CONFIRMATION_REQUESTED:
            return True
    return False


def _notify_tool_receipt_line(tool_name: str, result_preview: str) -> str | None:
    """One bullet for a notify-mode (no confirmation spec) tool result."""
    label = tool_action_receipt_label(tool_name)
    raw = (result_preview or "").strip()
    if not raw:
        return f"• {label}: (empty result)"
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return f"• {label}: (invalid JSON)"
    if not isinstance(obj, dict):
        return f"• {label}: {raw[:200]}{'…' if len(raw) > 200 else ''}"
    err = obj.get("error")
    if err is not None:
        return f"• {label}: {err}"
    msg = obj.get("message")
    if msg is not None and str(msg).strip():
        return f"• {label}: {msg}"
    status = obj.get("status")
    if status is not None and str(status).strip():
        extra = obj.get("job_id")
        if extra:
            return f"• {label}: {status} (`{extra}`)"
        return f"• {label}: {status}"
    uids = obj.get("user_ids")
    if isinstance(uids, list) and (tool_name or "").strip() == "list_usergroup_members":
        ug = obj.get("usergroup_id") or "?"
        return f"• {label}: {len(uids)} member(s) in `{ug}`"
    users = obj.get("users")
    if isinstance(users, list) and (tool_name or "").strip() == "list_users":
        return f"• {label}: {len(users)} match(es)"
    return f"• {label}: ok"


def _build_notify_mode_receipt(trace: list[ToolCallRecord]) -> str:
    lines: list[str] = []
    for rec in trace:
        name = rec.name or ""
        if get_tool_confirmation_spec(name) is not None:
            continue
        line = _notify_tool_receipt_line(name, rec.result_preview)
        if line:
            lines.append(line)
    return "\n".join(lines)


def _has_substantive_assistant_text(loop_out: ReactLoopResult) -> bool:
    return bool((loop_out.text or "").strip())


def _compose_post_loop_message(
    loop_out: ReactLoopResult, *, include_assistant_text: bool = True,
) -> str | None:
    """Build user-visible ephemeral body, or None if nothing to send."""
    receipt = _build_notify_mode_receipt(loop_out.tool_trace).strip()
    errors_block = (
        _format_tool_errors_ephemeral(loop_out.tool_errors)
        if loop_out.tool_errors
        else ""
    )
    assistant = (loop_out.text or "").strip()
    assistant_block = ""
    if include_assistant_text and assistant:
        assistant_block = assistant[:800] + ("…" if len(assistant) > 800 else "")

    sections: list[str] = []
    if assistant_block:
        sections.append(assistant_block)
    if receipt:
        sections.append(f"*Action(s) taken:*\n{receipt}")
    if errors_block:
        sections.append(errors_block)

    if sections:
        return "\n\n".join(sections)

    return None


def _format_tool_errors_ephemeral(tool_errors: list[str]) -> str:
    lines = "\n".join(f"• {line}" for line in tool_errors)
    return f"*Tool errors*\n{lines}"


def _slack_live_indications_notifier(
    channel_id: str,
    thread_ts: str,
    recipient_user_id: str,
) -> Callable[[AgentEvent], None]:
    """Agent-event hook; body is a stub until live Slack progress is implemented."""

    def on_agent_event(ev: AgentEvent) -> None:
        # TODO(live-indications): Call Slack here (e.g. ``slack_api`` or
        # ``copilot_user_notify.notify_progress`` / ``chat.postEphemeral``) using
        # ``channel_id``, ``thread_ts``, and ``recipient_user_id`` so the user sees
        # per-step feedback while tools run. Branch on ``ev.kind`` (``tool_result``,
        # ``assistant_tool_calls``, etc.); keep messages short to avoid rate limits.
        del ev, channel_id, thread_ts, recipient_user_id

    return on_agent_event


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
    forced_skill_folder: str | None = None,
    anchor_message_text: str | None = None,
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
        on_ev = _slack_live_indications_notifier(
            channel_id, thread_ts, recipient_user_id,
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
            forced_skill_folder=forced_skill_folder,
            anchor_message_text=anchor_message_text,
            on_agent_event=on_ev,
        )
    except ForcedSkillMissing:
        return
    except ThreadFetchError:
        copilot_user_notify.notify_error(
            channel_id,
            thread_ts,
            recipient_user_id,
            CHANNEL_INVITE_EPHEMERAL,
        )
        return
    except ReviseError as e:
        copilot_user_notify.notify_error(
            channel_id,
            thread_ts,
            recipient_user_id,
            str(e),
        )
        return
    except Exception as e:
        _logger.exception("run_react_and_confirm failed")
        header = _format_failure_message(copilot_trigger, copilot_action)
        detail = f"{type(e).__name__}: {e}".strip()
        copilot_user_notify.notify_error(
            channel_id,
            thread_ts,
            recipient_user_id,
            f"{header}\n{detail}" if detail else header,
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
    confirm_pending = _trace_shows_confirm_ui_pending(loop_out.tool_trace)
    body = _compose_post_loop_message(
        loop_out, include_assistant_text=not confirm_pending,
    )

    if confirm_pending:
        if body:
            copilot_user_notify.notify_react_feedback(
                channel_id,
                thread_ts,
                recipient_user_id,
                body,
            )
        return

    if body:
        copilot_user_notify.notify_react_feedback(
            channel_id,
            thread_ts,
            recipient_user_id,
            body,
        )
        return

    if not loop_out.tool_trace and not _has_substantive_assistant_text(loop_out):
        msg = _EMPTY_RUN_MSG
    else:
        msg = _NO_SUBMIT_MSG
    copilot_user_notify.notify_react_feedback(
        channel_id,
        thread_ts,
        recipient_user_id,
        msg,
    )
