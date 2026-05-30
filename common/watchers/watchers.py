"""Run all watchers: find one eligible thread per cfg, dispatch the configured skill."""

from __future__ import annotations

import logging
import time
from datetime import timezone
from typing import Any

from common.date_utils import parse_iso_datetime
from common.skill_runs import skill_runs
from common.slack.slack_api import slack_api
from common.watchers.eligible_thread_finder import iter_recent_thread_ids
from common.watchers.huey_app import huey
from common.watchers.watcher_config import SUPPORTED_TRIGGER, WatcherConfig
from common.watchers.watchers_root import load_all

_logger = logging.getLogger(__name__)


@huey.task()
@huey.lock_task("watchers")
def run_all_watchers(trigger: str = SUPPORTED_TRIGGER) -> None:
    """Single Huey task that iterates every watcher; per-watcher errors isolated."""
    for cfg in load_all():
        try:
            _evaluate_watcher(cfg)
        except Exception:
            _logger.exception("watcher %s failed", cfg.name)


def dispatch_watchers_async(trigger: str = SUPPORTED_TRIGGER) -> None:
    """Enqueue the watcher run; returns immediately (Slack listener path)."""
    run_all_watchers(trigger)


def run_watchers_for_trigger(trigger: str = SUPPORTED_TRIGGER) -> None:
    """Synchronous in-process variant for debugging / CLI ``watchers_run_once``."""
    for cfg in load_all():
        try:
            _evaluate_watcher(cfg)
        except Exception:
            _logger.exception("watcher %s failed", cfg.name)


def find_first_eligible_thread(cfg: WatcherConfig) -> str | None:
    oldest = time.time() - cfg.thread_started_after
    for thread_ts in iter_recent_thread_ids(cfg.channel_id, oldest):
        if _passes_filters(cfg, thread_ts):
            return thread_ts
    return None


def _evaluate_watcher(cfg: WatcherConfig) -> None:
    thread_ts = find_first_eligible_thread(cfg)
    if not thread_ts:
        return
    _run_skill_on_thread(cfg, thread_ts)


def _run_skill_on_thread(cfg: WatcherConfig, thread_ts: str) -> None:
    from common.slack.slack_bot.react_runner import run_react_and_confirm

    run_react_and_confirm(
        cfg.channel_id,
        thread_ts,
        cfg.requester_user_id,
        cfg.requester_user_id,
        "",
        context_kind="thread",
        forced_skill_folder=cfg.run_skill_id,
        copilot_trigger="watcher",
        copilot_action=f"watcher:{cfg.name}",
    )


def _passes_filters(cfg: WatcherConfig, thread_ts: str) -> bool:
    last_run_ts = _last_skill_run_epoch(cfg, thread_ts)
    if not _passes_skill_didnt_run_for(cfg, last_run_ts):
        return False
    messages = slack_api.read_thread(cfg.channel_id, thread_ts)
    if not _passes_messages_since_last_run(cfg, messages, last_run_ts):
        return False
    if not _passes_thread_quiet_longer_than(cfg, messages):
        return False
    return True


def _last_skill_run_epoch(cfg: WatcherConfig, thread_ts: str) -> float | None:
    row = skill_runs.find_latest_run(cfg.run_skill_id, cfg.channel_id, thread_ts)
    if not row:
        return None
    dt = parse_iso_datetime(row.get("action_ts"))
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _passes_skill_didnt_run_for(cfg: WatcherConfig, last_run_ts: float | None) -> bool:
    if last_run_ts is None:
        return True
    return (time.time() - last_run_ts) >= cfg.skill_didnt_run_for


def _passes_messages_since_last_run(
    cfg: WatcherConfig, messages: list[dict[str, Any]], last_run_ts: float | None,
) -> bool:
    count = _count_messages_since(messages, last_run_ts)
    return count > cfg.thread_had_more_than_x_messages_since_last_skill_run


def _count_messages_since(
    messages: list[dict[str, Any]], last_run_ts: float | None,
) -> int:
    if last_run_ts is None:
        return len(messages)
    return sum(1 for m in messages if _msg_epoch(m) > last_run_ts)


def _passes_thread_quiet_longer_than(
    cfg: WatcherConfig, messages: list[dict[str, Any]],
) -> bool:
    last_msg_ts = _last_message_epoch(messages)
    if last_msg_ts is None:
        return False
    return (time.time() - last_msg_ts) >= cfg.thread_quiet_for_x_seconds


def _msg_epoch(msg: dict[str, Any]) -> float:
    try:
        return float(msg.get("ts") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _last_message_epoch(messages: list[dict[str, Any]]) -> float | None:
    epochs = [_msg_epoch(m) for m in messages]
    epochs = [e for e in epochs if e > 0.0]
    return max(epochs) if epochs else None
