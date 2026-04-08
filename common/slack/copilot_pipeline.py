"""Shared copilot context building and ReAct loop for Slack."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from common.llm.llm_client import llm_client
from common.slack import agent_log
from common.progressive_disclosure import progressive_disclosure
from common.slack.slack_api import slack_api
from common.slack.slack_rag import slack_rag
from common.slack.thread_format import format_slack_thread_for_prompt
from common.tools.react_context import react_invocation_context
from common.tools.list_usergroup_members import (
    LIST_USERGROUP_MEMBERS_TOOL,
    handle_list_usergroup_members_call,
)
from common.tools.schedule_tool import SCHEDULE_PROMPT_TOOL, handle_schedule_prompt_call
from common.tools.send_slack_pm import SEND_SLACK_PM_TOOL, handle_send_slack_pm_call
from config.config import settings, parse_duration_seconds

DEFAULT_INSTRUCTION = "Draft a reply to this thread."
_SLACK_DIR = Path(__file__).resolve().parent
PROMPT_TEMPLATE = (_SLACK_DIR / "draft_prompt.md").read_text()
EXAMPLES_PATH = _SLACK_DIR / "example_threads.json"

_INTERACTIVE_TOOLS = [
    SCHEDULE_PROMPT_TOOL,
    SEND_SLACK_PM_TOOL,
    LIST_USERGROUP_MEMBERS_TOOL,
]


def _resolve_tools(
    tools: list[dict] | None,
    excluded_tools: list[dict] | None,
) -> list[dict]:
    if tools is not None:
        return tools
    if excluded_tools:
        return [t for t in _INTERACTIVE_TOOLS if not any(t is ex for ex in excluded_tools)]
    return _INTERACTIVE_TOOLS


class ThreadFetchError(Exception):
    """Raised when the Slack thread cannot be loaded (e.g. bot not in channel)."""


def fetch_thread_messages(channel_id: str, thread_ts: str) -> list[dict]:
    try:
        return slack_api.read_thread(channel_id, thread_ts)
    except Exception as exc:
        raise ThreadFetchError(str(exc)) from exc


def get_copilot_channel_context_limit() -> int:
    raw = settings.slack_bot.get("copilot_channel_context_limit", 30)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 30


def fetch_channel_tail_messages(
    channel_id: str, limit: int | None = None,
) -> list[dict]:
    """Recent channel messages in chronological order (oldest first)."""
    try:
        lim = limit if limit is not None else get_copilot_channel_context_limit()
        raw = slack_api.read_channel_history(channel_id, limit=lim)
        return list(reversed(raw))
    except Exception as exc:
        raise ThreadFetchError(str(exc)) from exc


def resolve_copilot_slack_context(
    channel_id: str, message: dict,
) -> tuple[str, list[dict]]:
    """Anchor ts for ephemerals + messages for the LLM (channel tail vs thread)."""
    ts = message["ts"]
    thread_ts = message.get("thread_ts")
    if not thread_ts:
        return ts, fetch_channel_tail_messages(channel_id)
    return thread_ts, fetch_thread_messages(channel_id, thread_ts)


def run_react_loop(
    channel_id: str,
    thread_ts: str,
    user_id: str,
    user_text: str,
    channel_name: str | None = None,
    tools: list[dict] | None = None,
    excluded_tools: list[dict] | None = None,
    tool_dispatch: Callable[[str, str], str] | None = None,
    thread_messages: list[dict] | None = None,
    copilot_trigger: str | None = None,
    copilot_action: str | None = None,
) -> str:
    if thread_messages is None:
        thread_messages = fetch_thread_messages(channel_id, thread_ts)
    skills = select_skills(thread_messages, user_text)
    thread_text = _thread_messages_text(thread_messages)
    rag_results = fetch_rag_context(channel_id, thread_ts, user_id, thread_messages)
    cross_rag_results = fetch_cross_channel_rag(
        channel_id, thread_ts, user_id, thread_text
    )
    examples = load_examples()
    agent_log_section = ""
    if copilot_trigger is not None and copilot_action is not None:
        prior = agent_log.read_recent_for_thread(
            channel_id, thread_ts, agent_log.llm_action_history_limit(),
        )
        agent_log_section = agent_log.format_agent_log_section(prior)
    prompt = compose_system_prompt(
        thread_messages,
        user_text,
        skills,
        rag_results,
        cross_rag_results,
        examples,
        channel_id=channel_id,
        thread_ts=thread_ts,
        channel_name=channel_name,
        agent_log_section=agent_log_section,
    )
    effective_tools = _resolve_tools(tools, excluded_tools)
    effective_dispatch = tool_dispatch or dispatch_copilot_tool
    with react_invocation_context(channel_id, thread_ts, user_id):
        loop_result = llm_client.agent_tool_loop(
            prompt,
            "Produce the draft reply. Use tools only when the user's skills require it.",
            effective_tools,
            effective_dispatch,
        )
    draft = loop_result.text
    if loop_result.tool_errors:
        err_lines = "\n".join(f"• {line}" for line in loop_result.tool_errors)
        draft = f"{draft}\n\n---\n*Tool errors*\n{err_lines}".strip()
    if copilot_trigger is not None and copilot_action is not None:
        summary = agent_log.summarize_copilot_run(
            trigger=copilot_trigger,
            action=copilot_action,
            user_text=user_text,
            final_text=draft,
            tool_trace=loop_result.tool_trace,
        )
        entry: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "channel": channel_id,
            "thread_ts": thread_ts,
            "trigger": copilot_trigger,
            "action": copilot_action,
            "summary": summary,
        }
        tools = agent_log.tool_trace_for_record(loop_result.tool_trace)
        if tools:
            entry["tools"] = tools
        agent_log.append_entry(entry)
    return draft


def dispatch_copilot_tool(name: str, arguments_json: str) -> str:
    if name == "schedule_prompt":
        return handle_schedule_prompt_call(arguments_json)
    if name == "send_slack_pm":
        return handle_send_slack_pm_call(arguments_json)
    if name == "list_usergroup_members":
        return handle_list_usergroup_members_call(arguments_json)
    return '{"error": "unknown tool"}'


# ---------------------------------------------------------------------------
# System prompt composition
# ---------------------------------------------------------------------------

def compose_system_prompt(
    thread_messages: list[dict],
    user_text: str,
    skills: list[str] | None = None,
    rag_results: list[dict] | None = None,
    cross_rag_results: list[dict] | None = None,
    examples: list[dict] | None = None,
    channel_id: str | None = None,
    thread_ts: str | None = None,
    channel_name: str | None = None,
    agent_log_section: str = "",
) -> str:
    channel_display = _channel_display_name(channel_name)
    agent_log_recent_thread_history = (
        (agent_log_section + "\n") if agent_log_section.strip() else ""
    )
    rendered = PROMPT_TEMPLATE.format(
        skills=_format_skills_section(skills),
        channel_context=_format_channel_rag_section(
            rag_results, channel_id, thread_ts, channel_display
        ),
        cross_channel_context=_format_cross_channel_rag_section(cross_rag_results),
        examples=_format_examples_section(examples),
        agent_log_recent_thread_history=agent_log_recent_thread_history,
        thread=_format_thread_for_prompt(
            thread_messages,
            channel_id=channel_id,
            thread_ts=thread_ts,
            channel_name=channel_name,
        ),
        instruction=user_text.strip() if user_text.strip() else DEFAULT_INSTRUCTION,
    )
    return _collapse_blank_lines(rendered)


def _channel_display_name(channel_name: str | None) -> str | None:
    if not channel_name or not channel_name.strip():
        return None
    cn = channel_name.strip()
    return cn if cn.startswith("#") else f"#{cn}"


def _format_skills_section(skills: list[str] | None) -> str:
    if not skills:
        return ""
    return _format_section("Skills", "\n\n".join(skills))


def _format_channel_rag_section(
    rag_results: list[dict] | None,
    channel_id: str | None,
    thread_ts: str | None,
    channel_display: str | None,
) -> str:
    if not rag_results:
        return ""
    if channel_id and thread_ts:
        text = slack_rag.format_rag_context_block(
            channel_id, thread_ts, rag_results,
            channel_display_name=channel_display,
        )
    else:
        text = "\n".join(f"- {r.get('text', '')}" for r in rag_results)
    return _format_section("Relevant Channel Context", text)


def _format_cross_channel_rag_section(cross_rag_results: list[dict] | None) -> str:
    if not cross_rag_results:
        return ""
    return _format_section(
        "Cross-Channel Context",
        slack_rag.format_cross_channel_rag_text(cross_rag_results),
    )


def _format_examples_section(examples: list[dict] | None) -> str:
    if not examples:
        return ""
    body = "\n".join(f"Q: {e['question']}\nA: {e['answer']}" for e in examples)
    return _format_section("Example Replies", body)


def _format_section(title: str, body: str) -> str:
    return f"## {title}\n{body}"


def _format_thread_for_prompt(
    messages: list[dict],
    *,
    channel_id: str | None,
    thread_ts: str | None,
    channel_name: str | None,
) -> str:
    return format_slack_thread_for_prompt(
        messages,
        channel_id=channel_id or "",
        thread_ts=thread_ts or "",
        channel_display_name=_channel_display_name(channel_name),
    )


# ---------------------------------------------------------------------------
# Context fetching helpers
# ---------------------------------------------------------------------------

def select_skills(thread_messages: list[dict], user_text: str) -> list[str]:
    skills = progressive_disclosure.select_skills("reply", thread_messages, user_text)
    if not skills:
        return [progressive_disclosure.get_default_instruction()]
    return skills


def fetch_rag_context(
    channel_id: str,
    thread_ts: str,
    user_id: str,
    thread_messages: list[dict],
) -> list[dict]:
    try:
        if not slack_rag.is_ready(channel_id):
            slack_api.send_ephemeral(
                channel_id, thread_ts, user_id,
                "Preparing RAG for this channel, will update when done.",
            )
            slack_rag.build(channel_id, get_checkpoint_seconds())
        return slack_rag.query_channel(channel_id, _thread_messages_text(thread_messages))
    except Exception:
        return []


def fetch_cross_channel_rag(
    channel_id: str,
    thread_ts: str,
    user_id: str,
    thread_context: str,
) -> list[dict]:
    cross_channels = get_cross_channel_ids()
    if not cross_channels:
        return []
    try:
        missing = slack_rag.missing_channels(cross_channels)
        if missing:
            names = ", ".join(missing)
            slack_api.send_ephemeral(
                channel_id, thread_ts, user_id,
                f"Creating RAG for {names}, please wait.",
            )
            checkpoint = get_checkpoint_seconds()
            for ch in missing:
                slack_rag.build(ch, checkpoint)
        return slack_rag.query_cross_channel(
            cross_channels, thread_context, exclude_channel=channel_id
        )
    except Exception:
        return []


def load_examples() -> list[dict]:
    if not EXAMPLES_PATH.exists():
        return []
    return json.loads(EXAMPLES_PATH.read_text())


def get_checkpoint_seconds() -> float:
    return parse_duration_seconds(settings.rag.checkpoint_duration)


def get_cross_channel_ids() -> list[str]:
    return list(settings.rag.cross_channel)


def _thread_messages_text(thread_messages: list[dict]) -> str:
    return " ".join(m.get("text", "") for m in thread_messages)


def _collapse_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text).strip()
