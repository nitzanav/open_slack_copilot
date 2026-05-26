"""Per-channel watcher config: parse + validate raw dict from ``<name>.json``."""

from __future__ import annotations

from dataclasses import dataclass

from common.progressive_disclosure.progressive_disclosure import is_safe_skill_folder_name

SUPPORTED_TRIGGER = "any_tool_confirmation"


@dataclass(frozen=True)
class WatcherConfig:
    name: str
    trigger: str
    requester_user_id: str
    channel_id: str
    run_skill_id: str
    thread_started_after: int
    skill_didnt_run_for: int
    thread_had_more_than_x_messages_since_last_skill_run: int
    thread_quiet_for_x_seconds: int


def validate_watcher_config(raw: dict, name: str) -> WatcherConfig:
    """Parse ``raw`` into ``WatcherConfig``; raises ``ValueError`` with a short message."""
    return WatcherConfig(
        name=_require_name(name),
        trigger=_require_trigger(raw),
        requester_user_id=_require_str(raw, "requester_user_id"),
        channel_id=_require_str(raw, "channel_id"),
        run_skill_id=_require_skill_id(raw),
        thread_started_after=_require_nonneg_int(raw, "thread_started_after"),
        skill_didnt_run_for=_require_nonneg_int(raw, "skill_didnt_run_for"),
        thread_had_more_than_x_messages_since_last_skill_run=_require_nonneg_int(
            raw, "thread_had_more_than_x_messages_since_last_skill_run",
        ),
        thread_quiet_for_x_seconds=_require_nonneg_int(raw, "thread_quiet_for_x_seconds"),
    )


def _require_name(name: str) -> str:
    n = (name or "").strip()
    if not n:
        raise ValueError("watcher name is empty")
    return n


def _require_trigger(raw: dict) -> str:
    trigger = (raw.get("trigger") or "").strip()
    if trigger != SUPPORTED_TRIGGER:
        raise ValueError(f"trigger must be {SUPPORTED_TRIGGER!r}, got {trigger!r}")
    return trigger


def _require_str(raw: dict, key: str) -> str:
    val = (raw.get(key) or "").strip() if isinstance(raw.get(key), str) else ""
    if not val:
        raise ValueError(f"{key} is required")
    return val


def _require_skill_id(raw: dict) -> str:
    sid = _require_str(raw, "run_skill_id")
    if not is_safe_skill_folder_name(sid):
        raise ValueError(f"run_skill_id is not a safe skill folder name: {sid!r}")
    return sid


def _require_nonneg_int(raw: dict, key: str) -> int:
    val = raw.get(key)
    if not isinstance(val, int) or isinstance(val, bool) or val < 0:
        raise ValueError(f"{key} must be a non-negative int")
    return val
