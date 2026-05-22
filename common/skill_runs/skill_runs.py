"""Persisted snapshot of a single ReAct loop run, keyed by thread_ts + action_ts.

One row per run is the source of truth for:
- the text and payload referenced by Slack confirm/revise buttons (replaces the
  previous on-disk draft cache and JSON-in-button compaction);
- the full step log used as an "example" when the run is thumbed up.
"""

from __future__ import annotations

from typing import Any

from common.data_layer import data_layer

COLLECTION = "skill_runs"


def _row_key(thread_ts: str, action_ts: str) -> str:
    return f"{(thread_ts or '').strip()}__{(action_ts or '').strip()}"


def _collection():
    return data_layer.get_collection(COLLECTION)


def init_run(
    *,
    skill_id: str | None,
    channel_id: str,
    thread_ts: str,
    action_ts: str,
    requester_user_id: str,
    tool_name: str,
    payload: dict[str, Any],
    text: str,
    conversation_id: str | None = None,
) -> str:
    key = _row_key(thread_ts, action_ts)
    row = {
        "skill_id": skill_id,
        "channel_id": channel_id,
        "thread_ts": thread_ts,
        "action_ts": action_ts,
        "requester_user_id": requester_user_id,
        "tool_name": tool_name,
        "payload": payload,
        "text": text,
        "conversation_id": conversation_id,
    }
    _collection().set(key, row)
    return (conversation_id or key).strip()


def enrich_with_run_log(key: str, run_log: dict[str, Any]) -> None:
    row = _collection().get(key)
    if not row:
        return
    row["run_log"] = run_log
    _collection().set(key, row)


def get(key: str) -> dict[str, Any] | None:
    return _collection().get(key)


def get_text(key: str) -> str:
    row = _collection().get(key) or {}
    return str(row.get("text") or "")


def get_payload(key: str) -> dict[str, Any]:
    row = _collection().get(key) or {}
    p = row.get("payload")
    return p if isinstance(p, dict) else {}


def get_skill_id(key: str) -> str | None:
    row = _collection().get(key) or {}
    sid = row.get("skill_id")
    return sid if isinstance(sid, str) and sid.strip() else None


def format_as_example(row: dict[str, Any]) -> str:
    """Render one thumbed-up run as a markdown example block (formatted on the fly)."""
    skill_id = row.get("skill_id") or "?"
    action_ts = row.get("action_ts") or "?"
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    instruction = str(payload.get("user_text") or payload.get("instruction") or "").strip()
    text = str(row.get("text") or "").strip()
    log = row.get("run_log") if isinstance(row.get("run_log"), dict) else {}
    tool_trace = log.get("tool_trace") if isinstance(log.get("tool_trace"), list) else []
    final_text = str(log.get("final_text") or "").strip()

    lines = [f"### Example: {skill_id} @ {action_ts}"]
    if instruction:
        lines.append(f"- Instruction: {instruction}")
    if tool_trace:
        names = ", ".join(
            (t.get("name") or "").strip() for t in tool_trace if isinstance(t, dict)
        )
        if names:
            lines.append(f"- Tools called: {names}")
    if text:
        lines.append("- Confirmed message:")
        lines.append("  ```")
        for line in text.splitlines() or [""]:
            lines.append(f"  {line}")
        lines.append("  ```")
    elif final_text:
        lines.append(f"- Final assistant text: {final_text}")
    return "\n".join(lines)
