"""End-to-end watcher run with mocked Slack + skill_runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from common.watchers import watchers, watchers_root
from common.watchers.watcher_config import SUPPORTED_TRIGGER


_NOW = 1_700_000_000.0


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _watcher_dict() -> dict:
    return {
        "trigger": SUPPORTED_TRIGGER,
        "requester_user_id": "U_REQ",
        "channel_id": "C1",
        "run_skill_id": "summarize_thread",
        "thread_started_after": 7 * 24 * 3600,
        "skill_didnt_run_for": 3600,
        "thread_had_more_than_x_messages_since_last_skill_run": 1,
        "thread_quiet_for_x_seconds": 600,
    }


@pytest.fixture
def isolated_data_root(tmp_path, monkeypatch):
    from config.config import settings
    settings.set("data_layer.root", str(tmp_path / "data"))
    yield tmp_path


def _history_page(thread_ids):
    return {
        "messages": [{"ts": tid} for tid in thread_ids],
        "response_metadata": {},
    }


def test_dispatches_skill_on_first_eligible_thread(isolated_data_root, monkeypatch):
    tmp = isolated_data_root
    watchers_dir = tmp / "watchers"
    watchers_dir.mkdir(parents=True)
    (watchers_dir / "summarize_active.json").write_text(json.dumps(_watcher_dict()))

    monkeypatch.setattr(watchers.time, "time", lambda: _NOW)
    monkeypatch.setattr(
        watchers_root, "watchers_root", lambda: watchers_dir,
    )

    slack_client = MagicMock()
    slack_client.conversations_history.return_value = _history_page(["100.0", "200.0"])
    threads = {
        "100.0": [  # too quiet check fails (recent reply)
            {"ts": f"{_NOW - 10_000:.6f}"},
            {"ts": f"{_NOW - 100:.6f}"},
        ],
        "200.0": [  # passes all
            {"ts": f"{_NOW - 5_000:.6f}"},
            {"ts": f"{_NOW - 800:.6f}"},
        ],
    }
    slack_client.conversations_replies.side_effect = lambda channel, ts: {
        "messages": threads[ts],
    }

    fake_runner = MagicMock()
    fake_module = MagicMock(run_react_and_confirm=fake_runner)
    monkeypatch.setitem(
        __import__("sys").modules,
        "common.slack.slack_bot.react_runner",
        fake_module,
    )

    with patch("common.watchers.eligible_thread_finder.slack_api.get_client",
               return_value=slack_client), \
         patch("common.slack.slack_api.slack_api.get_client",
               return_value=slack_client):
        watchers.run_watchers_for_trigger()

    fake_runner.assert_called_once()
    args = fake_runner.call_args.args
    kwargs = fake_runner.call_args.kwargs
    assert args[:2] == ("C1", "200.0")
    assert kwargs["forced_skill_folder"] == "summarize_thread"
    assert kwargs["copilot_action"] == "watcher:summarize_active"


def test_skips_when_last_skill_run_too_recent(isolated_data_root, monkeypatch):
    tmp = isolated_data_root
    watchers_dir = tmp / "watchers"
    watchers_dir.mkdir(parents=True)
    (watchers_dir / "w.json").write_text(json.dumps(_watcher_dict()))

    from common.skill_runs import skill_runs

    skill_runs.init_run(
        skill_id="summarize_thread",
        channel_id="C1",
        thread_ts="100.0",
        action_ts=_iso(_NOW - 60),
        requester_user_id="U_REQ",
        tool_name="t",
        payload={},
        text="",
    )

    monkeypatch.setattr(watchers.time, "time", lambda: _NOW)
    monkeypatch.setattr(watchers_root, "watchers_root", lambda: watchers_dir)

    slack_client = MagicMock()
    slack_client.conversations_history.return_value = _history_page(["100.0"])

    fake_runner = MagicMock()
    fake_module = MagicMock(run_react_and_confirm=fake_runner)
    monkeypatch.setitem(
        __import__("sys").modules,
        "common.slack.slack_bot.react_runner",
        fake_module,
    )

    with patch("common.watchers.eligible_thread_finder.slack_api.get_client",
               return_value=slack_client), \
         patch("common.slack.slack_api.slack_api.get_client",
               return_value=slack_client):
        watchers.run_watchers_for_trigger()

    slack_client.conversations_replies.assert_not_called()
    fake_runner.assert_not_called()
