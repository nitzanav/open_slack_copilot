"""Append one row to ``<data_root>/data/<skill_id>.csv``.

LLM passes a flat ``{column: value}`` JSON object. ``skill_id``, ``channel_name``,
``thread_ts`` and ``action_ts`` are injected from the invocation context.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from common.slack.slack_api import slack_api
from common.tools.copilot_tool import CopilotTool, register_copilot_tool
from common.tools.react_context import get_invocation
from config.config import settings

_TOOL_NAME = "append_csv_row"
_INJECTED_COLUMNS = ("skill_id", "channel_name", "thread_ts", "action_ts")


class _MissingSkillId(Exception):
    pass


APPEND_CSV_ROW_TOOL = {
    "type": "function",
    "function": {
        "name": _TOOL_NAME,
        "description": (
            "Append one row to the current skill's CSV log at "
            "<data_root>/data/<skill_id>.csv. Pass a flat object of "
            "{column_name: value} pairs. skill_id, channel_name, thread_ts and "
            "action_ts are added automatically from the current Slack context."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
    },
}


def _injected_row() -> dict[str, str]:
    inv = get_invocation() or {}
    channel_id = (inv.get("channel_id") or "").strip()
    return {
        "skill_id": (inv.get("skill_id") or "").strip(),
        "channel_name": slack_api.get_channel_prefixed_name(channel_id) if channel_id else "",
        "thread_ts": (inv.get("thread_ts") or "").strip(),
        "action_ts": (inv.get("action_ts") or "").strip(),
    }


def _csv_path(injected: dict[str, str]) -> Path:
    skill_id = injected.get("skill_id") or ""
    if not skill_id:
        raise _MissingSkillId("Missing skill_id in invocation context")
    if "/" in skill_id or skill_id in (".", ".."):
        raise _MissingSkillId("Invalid skill_id in invocation context")
    root = Path(str(settings.get("data_layer", {}).get("root", "~/.open_slack_copilot"))).expanduser()
    return root / "data" / f"{skill_id}.csv"


def _read_header(path: Path) -> list[str] | None:
    if not path.exists():
        return None
    with path.open("r", newline="", encoding="utf-8") as f:
        return next(csv.reader(f), None)


def _write_row(path: Path, header: list[str], row: dict[str, str], *, write_header: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if write_header else "a"
    with path.open(mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow({col: row.get(col, "") for col in header})


def _initial_header(user_fields: dict[str, str]) -> list[str]:
    extra = [k for k in user_fields if k not in _INJECTED_COLUMNS]
    return list(_INJECTED_COLUMNS) + extra


def _write_header_if_not_exists(path: Path, user_fields: dict[str, str]) -> tuple[list[str], bool]:
    header = _read_header(path)
    if header is None:
        return _initial_header(user_fields), True
    return header, False


def _invoke(arguments_json: str) -> str:
    user_fields = {str(k): "" if v is None else str(v) for k, v in json.loads(arguments_json or "{}").items()}
    injected = _injected_row()
    try:
        path = _csv_path(injected)
    except _MissingSkillId as e:
        return json.dumps({"error": str(e)})

    row = {**user_fields, **injected}
    header, write_header = _write_header_if_not_exists(path, user_fields)
    _write_row(path, header, row, write_header=write_header)

    return json.dumps({"status": "appended", "path": str(path), "columns": header})


APPEND_CSV_ROW = CopilotTool(
    name=_TOOL_NAME,
    llm_schema=APPEND_CSV_ROW_TOOL,
    handle=_invoke,
    action_receipt_label="CSV row appended",
)

register_copilot_tool(APPEND_CSV_ROW)
