"""Append-only agent log (NDJSON) under agent_logs/ + summarization for each copilot run."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common.llm.llm_client import llm_client
from config.config import settings

_REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_LOG_CONFIG = settings.agent_log
AGENT_LOGS_DIR = _REPO_ROOT / AGENT_LOG_CONFIG.get("agent_logs_dir", "agent_logs")
GLOBAL_LOG = AGENT_LOGS_DIR / AGENT_LOG_CONFIG.get("global_log_filename", "llm_actions.log")
_MAX_TOOL_SNIPPET = AGENT_LOG_CONFIG.get("max_tool_snippet", 600)
_MAX_TOOL_PREVIEW_IN_LOG = AGENT_LOG_CONFIG.get("max_tool_preview_in_log", 400)
_SHORT_FINAL_SKIP_SUMMARY_LLM_CHARS = AGENT_LOG_CONFIG.get("short_final_skip_summary_llm_chars", 100)
_WRITE_LOCK = threading.Lock()


def agent_logs_root() -> Path:
    return AGENT_LOGS_DIR


def thread_log_path(channel_id: str, thread_ts: str) -> Path:
    return (
        AGENT_LOGS_DIR
        / "channel"
        / channel_id
        / "thread"
        / thread_ts
        / "llm_actions.log"
    )


def _display_enum(s: str) -> str:
    return (s or "").replace("_", " ").strip()


def _bracket_utc(ts_iso: str) -> str:
    try:
        raw = (ts_iso or "").strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return "unknown time"


def _tool_names_from_record(entry: dict) -> list[str]:
    tools = entry.get("tools")
    if not isinstance(tools, list):
        return []
    names: list[str] = []
    for t in tools:
        if isinstance(t, dict):
            n = str(t.get("name", "")).strip()
            if n:
                names.append(n)
    return names


def format_agent_log_section(entries: list[dict]) -> str:
    """Build ## Agent log subsection for the system prompt (compact, no channel/thread per line)."""
    if not entries:
        return ""
    lines: list[str] = ["## Agent log", ""]
    for e in entries:
        ts = _bracket_utc(str(e.get("timestamp", "")))
        trig = _display_enum(str(e.get("trigger", "")))
        act = _display_enum(str(e.get("action", "")))
        summ = str(e.get("summary", "")).strip()
        row = f"[{ts}] {trig} - {act}: {summ}"
        tnames = _tool_names_from_record(e)
        if tnames:
            row += f" | tools: {', '.join(tnames)}"
        lines.append(row)
    return "\n".join(lines) + "\n"


def read_recent_for_thread(channel_id: str, thread_ts: str, limit: int) -> list[dict]:
    path = thread_log_path(channel_id, thread_ts)
    if not path.is_file():
        return []
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    parsed: list[dict] = []
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                parsed.append(obj)
        except json.JSONDecodeError:
            continue
    if limit <= 0:
        return []
    return parsed[-limit:]


def append_entry(record: dict) -> None:
    line = json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"
    thread_path = thread_log_path(
        str(record.get("channel", "")),
        str(record.get("thread_ts", "")),
    )
    with _WRITE_LOCK:
        AGENT_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        GLOBAL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with GLOBAL_LOG.open("a", encoding="utf-8") as g:
            g.write(line)
        thread_path.parent.mkdir(parents=True, exist_ok=True)
        with thread_path.open("a", encoding="utf-8") as t:
            t.write(line)


def _truncate(s: str, max_len: int) -> str:
    s = (s or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def tool_trace_for_record(trace: list[Any]) -> list[dict[str, str]]:
    """JSON-serializable tool rows for NDJSON (name + truncated result preview)."""
    out: list[dict[str, str]] = []
    for item in trace:
        name = getattr(item, "name", "") or ""
        prev = getattr(item, "result_preview", "") or ""
        if not name and not prev:
            continue
        out.append({
            "name": name,
            "result_preview": _truncate(prev, _MAX_TOOL_PREVIEW_IN_LOG),
        })
    return out


def _tool_trace_lines(trace: list[Any]) -> str:
    if not trace:
        return "(none)"
    parts: list[str] = []
    for item in trace:
        name = getattr(item, "name", "") or ""
        prev = getattr(item, "result_preview", "") or ""
        parts.append(f"- {name}: {_truncate(prev, _MAX_TOOL_SNIPPET)}")
    return "\n".join(parts)


def _fallback_summary(
    trigger: str,
    action: str,
    user_text: str,
    trace: list[Any],
) -> str:
    names = [getattr(t, "name", "") for t in trace]
    if "schedule_prompt" in names:
        return "Scheduled a recurring prompt for this thread"
    if "send_slack_pm" in names:
        return "Sent or queued a direct message via Slack"
    if "list_usergroup_members" in names:
        return "Listed user group members for the draft"
    ut = _truncate(user_text, 80)
    if ut:
        return f"Processed instruction: {ut}"
    return "Copilot run completed"


_SUMMARY_WORDS_RE = re.compile(r"\s+")


def _word_count(s: str) -> int:
    return len([w for w in _SUMMARY_WORDS_RE.split(s.strip()) if w])


def _clamp_summary_words(s: str, max_words: int = 20) -> str:
    words = [w for w in _SUMMARY_WORDS_RE.split((s or "").strip()) if w]
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words])


def summarize_copilot_run(
    *,
    trigger: str,
    action: str,
    user_text: str,
    final_text: str,
    tool_trace: list[Any],
) -> str:
    ft = (final_text or "").strip()
    if ft and len(ft) < _SHORT_FINAL_SKIP_SUMMARY_LLM_CHARS:
        return _clamp_summary_words(ft, 20)

    system = (
        "You write an extremely brief log line for a Slack copilot run. "
        "Output ONLY plain text: 2 to 20 words, no quotes, no JSON. "
        "Describe the main outcome: the draft or revision, OR a scheduled prompt being set up, "
        "OR a reminder/DM being sent — whichever mattered most. "
        "If tools ran but the user-visible result is still a draft, say what the draft did."
    )
    user_payload = (
        f"trigger: {trigger}\n"
        f"action: {action}\n"
        f"user_instruction:\n{_truncate(user_text, 2000)}\n\n"
        f"final_assistant_text:\n{_truncate(ft, 2000)}\n\n"
        f"tool_calls (name and result snippets):\n{_tool_trace_lines(tool_trace)}"
    )
    try:
        out = (llm_client.generate(system, user_payload) or "").strip()
        out = out.strip("\"'")
        if 1 <= _word_count(out) <= 24:
            return out
        if out and _word_count(out) > 24:
            words = [w for w in _SUMMARY_WORDS_RE.split(out) if w][:20]
            return " ".join(words) if words else _fallback_summary(
                trigger, action, user_text, tool_trace
            )
    except Exception:
        pass
    return _fallback_summary(trigger, action, user_text, tool_trace)


def llm_action_history_limit() -> int:
    raw = settings.slack_bot.get("llm_action_history_limit", 10)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 10
    return max(1, min(n, 50))
