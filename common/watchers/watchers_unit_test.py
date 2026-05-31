"""Filter logic for ``find_first_eligible_thread`` and dispatch."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from common.watchers import watchers
from common.watchers.watcher_config import SUPPORTED_TRIGGER, WatcherConfig


_FIXED_NOW = 1_700_000_000.0


def _cfg(**overrides) -> WatcherConfig:
    base = dict(
        name="w1",
        trigger=SUPPORTED_TRIGGER,
        requester_user_id="U_REQ",
        channel_id="C1",
        run_skill_id="summarize_thread",
        thread_started_after=7 * 24 * 3600,
        skill_didnt_run_for=2 * 3600,
        thread_had_more_than_x_messages_since_last_skill_run=2,
        thread_quiet_for_x_seconds=600,
    )
    base.update(overrides)
    return WatcherConfig(**base)


def _patch_now(monkeypatch, now: float = _FIXED_NOW) -> None:
    monkeypatch.setattr(watchers.time, "time", lambda: now)


def _msg(ts: float) -> dict:
    return {"ts": f"{ts:.6f}"}


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def test_skipped_when_last_run_too_recent(monkeypatch):
    _patch_now(monkeypatch)
    cfg = _cfg()
    last_run_iso = _iso(_FIXED_NOW - 600)
    with patch.object(watchers.skill_runs, "find_latest_run", return_value={"action_ts": last_run_iso}):
        assert watchers._passes_filters(cfg, "100.0") is False


def test_skipped_when_too_few_new_messages(monkeypatch):
    _patch_now(monkeypatch)
    cfg = _cfg(thread_had_more_than_x_messages_since_last_skill_run=2)
    last_run_iso = _iso(_FIXED_NOW - 10_000)
    messages = [
        _msg(_FIXED_NOW - 11_000),
        _msg(_FIXED_NOW - 9_000),
        _msg(_FIXED_NOW - 8_000),
    ]
    with patch.object(watchers.skill_runs, "find_latest_run", return_value={"action_ts": last_run_iso}), \
         patch.object(watchers.slack_api, "read_thread", return_value=messages):
        assert watchers._passes_filters(cfg, "100.0") is False


def test_skipped_when_thread_not_quiet(monkeypatch):
    _patch_now(monkeypatch)
    cfg = _cfg(thread_quiet_for_x_seconds=600,
               thread_had_more_than_x_messages_since_last_skill_run=1)
    messages = [
        _msg(_FIXED_NOW - 5_000),
        _msg(_FIXED_NOW - 100),
    ]
    with patch.object(watchers.skill_runs, "find_latest_run", return_value=None), \
         patch.object(watchers.slack_api, "read_thread", return_value=messages):
        assert watchers._passes_filters(cfg, "100.0") is False


def test_passes_all_filters(monkeypatch):
    _patch_now(monkeypatch)
    cfg = _cfg(skill_didnt_run_for=3600,
               thread_had_more_than_x_messages_since_last_skill_run=1,
               thread_quiet_for_x_seconds=600)
    last_run_iso = _iso(_FIXED_NOW - 10_000)
    messages = [
        _msg(_FIXED_NOW - 9_000),
        _msg(_FIXED_NOW - 8_000),
        _msg(_FIXED_NOW - 700),
    ]
    with patch.object(watchers.skill_runs, "find_latest_run", return_value={"action_ts": last_run_iso}), \
         patch.object(watchers.slack_api, "read_thread", return_value=messages):
        assert watchers._passes_filters(cfg, "100.0") is True


def test_passes_when_no_prior_run(monkeypatch):
    _patch_now(monkeypatch)
    cfg = _cfg(thread_had_more_than_x_messages_since_last_skill_run=1,
               thread_quiet_for_x_seconds=300)
    messages = [
        _msg(_FIXED_NOW - 5_000),
        _msg(_FIXED_NOW - 1_000),
    ]
    with patch.object(watchers.skill_runs, "find_latest_run", return_value=None), \
         patch.object(watchers.slack_api, "read_thread", return_value=messages):
        assert watchers._passes_filters(cfg, "100.0") is True


def test_skipped_when_too_few_messages_and_no_prior_run(monkeypatch):
    _patch_now(monkeypatch)
    cfg = _cfg(
        thread_had_more_than_x_messages_since_last_skill_run=3,
        thread_quiet_for_x_seconds=300,
    )
    messages = [_msg(_FIXED_NOW - 1_000)]
    with patch.object(watchers.skill_runs, "find_latest_run", return_value=None), \
         patch.object(watchers.slack_api, "read_thread", return_value=messages):
        assert watchers._passes_filters(cfg, "100.0") is False


def test_skill_didnt_run_for_short_circuits_without_reading_thread(monkeypatch):
    _patch_now(monkeypatch)
    cfg = _cfg()
    last_run_iso = _iso(_FIXED_NOW - 60)
    read_thread = MagicMock()
    with patch.object(watchers.skill_runs, "find_latest_run", return_value={"action_ts": last_run_iso}), \
         patch.object(watchers.slack_api, "read_thread", read_thread):
        watchers._passes_filters(cfg, "100.0")
    read_thread.assert_not_called()


def test_find_first_eligible_thread_picks_first_passing(monkeypatch):
    _patch_now(monkeypatch)
    cfg = _cfg()
    thread_ids = iter(["100.0", "200.0", "300.0"])
    passes_per_id = {"100.0": False, "200.0": True, "300.0": False}
    with patch.object(watchers, "iter_recent_thread_ids", return_value=thread_ids), \
         patch.object(watchers, "_passes_filters", side_effect=lambda c, t: passes_per_id[t]):
        assert watchers.find_first_eligible_thread(cfg) == "200.0"


def test_find_first_eligible_thread_returns_none_when_no_match(monkeypatch):
    _patch_now(monkeypatch)
    cfg = _cfg()
    with patch.object(watchers, "iter_recent_thread_ids", return_value=iter(["100.0"])), \
         patch.object(watchers, "_passes_filters", return_value=False):
        assert watchers.find_first_eligible_thread(cfg) is None


def test_evaluate_watcher_dispatches_run_react_and_confirm(monkeypatch):
    _patch_now(monkeypatch)
    cfg = _cfg(name="watch1")
    fake_runner = MagicMock()
    fake_module = MagicMock(run_react_and_confirm=fake_runner)
    monkeypatch.setitem(
        __import__("sys").modules,
        "common.slack.slack_bot.react_runner",
        fake_module,
    )
    with patch.object(watchers, "find_first_eligible_thread", return_value="100.0"):
        watchers._evaluate_watcher(cfg)
    fake_runner.assert_called_once()
    call_kwargs = fake_runner.call_args
    args = call_kwargs.args
    kwargs = call_kwargs.kwargs
    assert args[:2] == ("C1", "100.0")
    assert args[2] == cfg.requester_user_id  # recipient
    assert args[3] == cfg.requester_user_id  # prepare
    assert args[4] == ""
    assert kwargs["context_kind"] == "thread"
    assert kwargs["forced_skill_folder"] == "summarize_thread"
    assert kwargs["copilot_trigger"] == "watcher"
    assert kwargs["copilot_action"] == "watcher:watch1"


def test_evaluate_watcher_noop_when_no_eligible_thread(monkeypatch):
    cfg = _cfg()
    fake_runner = MagicMock()
    fake_module = MagicMock(run_react_and_confirm=fake_runner)
    monkeypatch.setitem(
        __import__("sys").modules,
        "common.slack.slack_bot.react_runner",
        fake_module,
    )
    with patch.object(watchers, "find_first_eligible_thread", return_value=None):
        watchers._evaluate_watcher(cfg)
    fake_runner.assert_not_called()


def test_run_watchers_for_trigger_isolates_per_watcher_errors(monkeypatch):
    cfg_ok = _cfg(name="good")
    cfg_bad = _cfg(name="bad")
    seen: list[str] = []

    def evaluate(cfg):
        seen.append(cfg.name)
        if cfg.name == "bad":
            raise RuntimeError("boom")

    with patch.object(watchers, "load_all", return_value=[cfg_bad, cfg_ok]), \
         patch.object(watchers, "_evaluate_watcher", side_effect=evaluate):
        watchers.run_watchers_for_trigger()
    assert seen == ["bad", "good"]
