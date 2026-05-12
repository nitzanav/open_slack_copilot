"""Shared copilot context building and ReAct loop for Slack."""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from common.llm.llm_client import llm_client
from common.llm.llm_apis.types import AgentEventNotifier
from common.slack import agent_log
from common.progressive_disclosure import progressive_disclosure
from common.skill_runs import skill_runs
from common.slack import copilot_user_notify
from common.slack.slack_api import slack_api
from common.slack.slack_rag import slack_rag
from common.slack.thread_format import format_slack_thread_for_prompt
from common.tools.react_context import react_invocation_context
from common.tools.append_csv_row import APPEND_CSV_ROW_TOOL
from common.tools.copilot_tool import dispatch_copilot_tool as dispatch_registered_copilot_tool
from common.tools.list_usergroup_members import LIST_USERGROUP_MEMBERS_TOOL
from common.tools.list_users import LIST_USERS_TOOL
from common.tools.schedule_tool import SCHEDULE_PROMPT_TOOL
from common.tools.send_ephemeral_message import SEND_EPHEMERAL_MESSAGE_TOOL
from common.tools.send_dm_as_app import SEND_DM_AS_APP_TOOL
from common.tools.send_thread_reply_as_app import SEND_THREAD_REPLY_AS_APP_TOOL
from common.tools.send_thread_reply_on_behalf_of_requester import (
    SEND_THREAD_REPLY_ON_BEHALF_OF_REQUESTER_TOOL,
)
from config.config import settings, parse_duration_seconds

DEFAULT_INSTRUCTION = "Draft a reply to this thread."
_SLACK_DIR = Path(__file__).resolve().parent
PROMPT_TEMPLATE = (_SLACK_DIR / "draft_prompt.md").read_text()
EXAMPLES_PATH = _SLACK_DIR / "example_threads.json"

_INTERACTIVE_TOOLS = [
    SCHEDULE_PROMPT_TOOL,
    SEND_DM_AS_APP_TOOL,
    SEND_THREAD_REPLY_ON_BEHALF_OF_REQUESTER_TOOL,
    SEND_THREAD_REPLY_AS_APP_TOOL,
    SEND_EPHEMERAL_MESSAGE_TOOL,
    LIST_USERGROUP_MEMBERS_TOOL,
    LIST_USERS_TOOL,
    APPEND_CSV_ROW_TOOL,
]


@dataclass
class ReactLoopResult:
    """Outcome of ``run_react_loop`` / ``run_react_loop_with_selected_skill``."""

    text: str
    tool_trace: list[Any] = field(default_factory=list)
    tool_errors: list[str] = field(default_factory=list)


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


# Slack message shortcuts: ``callback_id`` is ``slack_copilot_<reply_skill_folder>`` (see README).
MESSAGE_SHORTCUT_CALLBACK_PREFIX = "slack_copilot_"
MESSAGE_SHORTCUT_CALLBACK_PATTERN = re.compile(
    r"^slack_copilot_[a-zA-Z_-]+\Z",
)


class ForcedReplySkillMissing(Exception):
    """Forced reply skill folder has no ``SKILL.md`` (or was removed after the modal opened)."""


def load_forced_reply_skill(skill_folder: str) -> tuple[str, str] | None:
    """Load ``reply/<skill_folder>/SKILL.md`` (same rules as progressive disclosure)."""
    return progressive_disclosure.load_forced_reply_skill(skill_folder)


def reply_skill_folder_from_slack_message_shortcut(callback_id: str) -> str | None:
    """Resolve ``reply/<folder>/`` folder name from a message shortcut ``callback_id``, or None."""
    cid = (callback_id or "").strip()
    if not MESSAGE_SHORTCUT_CALLBACK_PATTERN.match(cid):
        return None
    suffix = cid.removeprefix(MESSAGE_SHORTCUT_CALLBACK_PREFIX)
    if not progressive_disclosure.is_safe_reply_skill_folder_name(suffix):
        return None
    if load_forced_reply_skill(suffix) is None:
        return None
    return suffix


def reply_skill_folder_valid_for_forced_modal(folder: str) -> bool:
    """True when ``folder`` is safe and ``reply/<folder>/SKILL.md`` exists (modal submit guard)."""
    f = (folder or "").strip()
    if not progressive_disclosure.is_safe_reply_skill_folder_name(f):
        return False
    return load_forced_reply_skill(f) is not None


def select_skill(
    thread_messages: list[dict],
    user_text: str,
    skill_type: str = "reply",
) -> tuple[str, str] | None:
    """Pick one installed skill via progressive disclosure (LLM stages)."""
    return progressive_disclosure.select_single_skill(
        skill_type, thread_messages, user_text,
    )


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
    *,
    context_kind: str = "thread",
    forced_reply_skill_folder: str | None = None,
    on_agent_event: AgentEventNotifier | None = None,
) -> ReactLoopResult:
    if thread_messages is None:
        thread_messages = fetch_thread_messages(channel_id, thread_ts)
    if forced_reply_skill_folder is not None:
        selected = load_forced_reply_skill(forced_reply_skill_folder)
        if selected is None:
            raise ForcedReplySkillMissing
        return run_react_loop_with_selected_skill(
            channel_id,
            thread_ts,
            user_id,
            user_text,
            selected,
            channel_name=channel_name,
            tools=tools,
            excluded_tools=excluded_tools,
            tool_dispatch=tool_dispatch,
            thread_messages=thread_messages,
            copilot_trigger=copilot_trigger,
            copilot_action=copilot_action,
            context_kind=context_kind,
            on_agent_event=on_agent_event,
        )
    picked = select_skill(thread_messages, user_text)
    return run_react_loop_with_selected_skill(
        channel_id,
        thread_ts,
        user_id,
        user_text,
        picked,
        channel_name=channel_name,
        tools=tools,
        excluded_tools=excluded_tools,
        tool_dispatch=tool_dispatch,
        thread_messages=thread_messages,
        copilot_trigger=copilot_trigger,
        copilot_action=copilot_action,
        context_kind=context_kind,
        on_agent_event=on_agent_event,
    )


def run_react_loop_with_selected_skill(
    channel_id: str,
    thread_ts: str,
    user_id: str,
    user_text: str,
    selected_skill: tuple[str, str] | None,
    channel_name: str | None = None,
    tools: list[dict] | None = None,
    excluded_tools: list[dict] | None = None,
    tool_dispatch: Callable[[str, str], str] | None = None,
    thread_messages: list[dict] | None = None,
    copilot_trigger: str | None = None,
    copilot_action: str | None = None,
    *,
    context_kind: str = "thread",
    on_agent_event: AgentEventNotifier | None = None,
) -> ReactLoopResult:
    if thread_messages is None:
        thread_messages = fetch_thread_messages(channel_id, thread_ts)
    if selected_skill is not None:
        skill_id, skill_text = selected_skill
        _notify_skill_selection(channel_id, thread_ts, user_id, skill_id)
        skills = [skill_text]
    else:
        skill_id = None
        skills = []
    action_ts = datetime.now(timezone.utc).isoformat()
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
    bot_uid = slack_api.get_bot_user_id()
    tool_extra = (
        "Thread reply tool selection (mandatory rules):\n"
        "- Default: call `send_thread_reply_on_behalf_of_requester`. Use it whenever the requester asks "
        "you to write/draft/send a message in the thread, including phrasings like 'reply', 'answer', "
        "'send from me', 'in my name', 'on my behalf', or any first-person message authored for them.\n"
        "- Only call `send_thread_reply_as_app` when the message is an automated reminder, nudge, or "
        "notification that the bot itself is announcing (e.g. scheduled reminders, system notices). "
        "Never use it for messages the requester would naturally say themselves.\n"
        "If unsure, choose `send_thread_reply_on_behalf_of_requester`. The requester confirms in Slack "
        "before anything is posted; if user OAuth is not connected, they get instructions to connect.\n"
        "If no public thread message is needed (only scheduling/lookup tools), do not call any thread-reply tool. "
        "Use `schedule_prompt`, `send_dm_as_app`, `list_usergroup_members`, `list_users`, etc., when the selected skills require them."
    )
    if bot_uid:
        tool_extra += f" Never mention `<@{bot_uid}>` in tool messages — that id is this app."
    with react_invocation_context(
        channel_id, thread_ts, user_id,
        context_kind=context_kind,
        skill_id=skill_id,
        action_ts=action_ts,
    ):
        loop_result = llm_client.agent_tool_loop(
            prompt,
            tool_extra,
            effective_tools,
            effective_dispatch,
            on_agent_event=on_agent_event,
        )
    draft = loop_result.text
    raw_tool_errors = list(loop_result.tool_errors)
    if loop_result.tool_errors:
        err_lines = "\n".join(f"• {line}" for line in loop_result.tool_errors)
        draft = f"{draft}\n\n---\n*Tool errors*\n{err_lines}".strip()
    _enrich_skill_runs_row(
        thread_ts, action_ts, thread_messages, loop_result, draft,
    )
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
    return ReactLoopResult(
        text=draft,
        tool_trace=list(loop_result.tool_trace),
        tool_errors=raw_tool_errors,
    )


def _enrich_skill_runs_row(
    thread_ts: str,
    action_ts: str,
    thread_messages: list[dict],
    loop_result,
    final_text: str,
) -> None:
    """Persist the run log onto the matching skill_runs row if one was written."""
    try:
        key = skill_runs._row_key(thread_ts, action_ts)
        if skill_runs.get(key) is None:
            return
        run_log = {
            "tool_trace": agent_log.tool_trace_for_record(loop_result.tool_trace),
            "tool_errors": list(loop_result.tool_errors),
            "final_text": final_text,
            "thread_excerpt": [
                {"user": m.get("user", ""), "text": m.get("text", "")}
                for m in thread_messages[-10:]
            ],
        }
        skill_runs.enrich_with_run_log(key, run_log)
    except Exception:
        pass


def _notify_skill_selection(
    channel_id: str, thread_ts: str, user_id: str, skill_id: str,
) -> None:
    try:
        copilot_user_notify.notify_progress(
            channel_id, thread_ts, user_id, f"Selected skill: `{skill_id}`",
        )
    except Exception:
        pass


def dispatch_copilot_tool(name: str, arguments_json: str) -> str:
    out = dispatch_registered_copilot_tool(name, arguments_json)
    if out is not None:
        return out
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

def fetch_rag_context(
    channel_id: str,
    thread_ts: str,
    user_id: str,
    thread_messages: list[dict],
) -> list[dict]:
    try:
        if not slack_rag.is_ready(channel_id):
            copilot_user_notify.notify_progress(
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
            copilot_user_notify.notify_progress(
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
