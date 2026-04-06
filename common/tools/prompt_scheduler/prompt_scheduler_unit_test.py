import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from common.tools.prompt_scheduler import prompt_scheduler as sched


@pytest.fixture(autouse=True)
def _reset_scheduler():
    yield
    sched.shutdown_scheduler()
    sched._scheduler = None  # noqa: SLF001


def _write_job(base: Path, job_id: str, meta: dict, prompt: str = "Check thread."):
    d = base / job_id
    d.mkdir(parents=True)
    (d / "metadata.json").write_text(json.dumps(meta))
    (d / "prompt.txt").write_text(prompt)


def _future_meta(**overrides) -> dict:
    now = datetime.now(timezone.utc)
    meta = {
        "thread_ts": "T1",
        "channel_id": "C1",
        "user_id": "U1",
        "cron": "0 9 * * *",
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(days=7)).isoformat().replace("+00:00", "Z"),
    }
    meta.update(overrides)
    return meta


@patch("common.tools.prompt_scheduler.prompt_scheduler.run_react_and_confirm")
def test_run_calls_react_loop_with_prompt(mock_send, tmp_path, monkeypatch):
    monkeypatch.setattr(sched, "scheduled_prompts_root", lambda: tmp_path)
    prompt_text = "Remind everyone about the deadline."
    _write_job(tmp_path, "sched_ok", _future_meta(), prompt=prompt_text)

    sched.run_scheduled_prompt("sched_ok")

    mock_send.assert_called_once()
    call_kw = mock_send.call_args
    assert call_kw[0] == ("C1", "T1", "U1", "U1", prompt_text)
    assert call_kw[1]["context_kind"] == "thread"
    from common.tools.schedule_tool import SCHEDULE_PROMPT_TOOL

    assert call_kw[1]["excluded_tools"] == [SCHEDULE_PROMPT_TOOL]


@patch("common.tools.prompt_scheduler.prompt_scheduler.remove_job")
def test_expiration_removes_job(mock_remove, tmp_path, monkeypatch):
    monkeypatch.setattr(sched, "scheduled_prompts_root", lambda: tmp_path)
    past = datetime.now(timezone.utc) - timedelta(days=1)
    meta = _future_meta(
        expires_at=past.isoformat().replace("+00:00", "Z"),
    )
    _write_job(tmp_path, "sched_exp", meta)

    sched.run_scheduled_prompt("sched_exp")

    mock_remove.assert_called_once_with("sched_exp", delete_files=True)


@patch("common.slack.slack_bot.react_runner.fetch_thread_messages")
@patch("common.tools.prompt_scheduler.prompt_scheduler.remove_job")
@patch("common.slack.slack_bot.react_runner.slack_api")
def test_thread_inaccessible_sends_invite_does_not_remove_job(
    mock_slack, mock_remove, mock_fetch, tmp_path, monkeypatch,
):
    monkeypatch.setattr(sched, "scheduled_prompts_root", lambda: tmp_path)
    _write_job(tmp_path, "sched_bad", _future_meta())
    from common.slack.copilot_pipeline import ThreadFetchError
    from common.slack.slack_bot.react_runner import CHANNEL_INVITE_EPHEMERAL

    mock_fetch.side_effect = ThreadFetchError("gone")

    sched.run_scheduled_prompt("sched_bad")

    mock_remove.assert_not_called()
    mock_slack.send_ephemeral.assert_called_once_with(
        "C1", "T1", "U1", CHANNEL_INVITE_EPHEMERAL,
    )


@patch("common.slack.slack_bot.react_runner.fetch_thread_messages")
@patch("common.slack.slack_bot.react_runner.run_react_loop")
@patch("common.slack.slack_bot.thread_reply_confirmation.send_reply_confirmation")
def test_result_sent_to_scheduling_user(mock_send_confirm, mock_react, mock_fetch, tmp_path, monkeypatch):
    monkeypatch.setattr(sched, "scheduled_prompts_root", lambda: tmp_path)
    _write_job(tmp_path, "sched_user", _future_meta())
    mock_fetch.return_value = []
    mock_react.return_value = "Here is the reply"

    sched.run_scheduled_prompt("sched_user")

    mock_send_confirm.assert_called_once_with(
        "C1",
        "T1",
        "U1",
        "U1",
        "Here is the reply",
        context_kind="thread",
    )


def test_print_scheduled_prompt_jobs_lists_job(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sched, "scheduled_prompts_root", lambda: tmp_path)
    _write_job(tmp_path, "sched_list_test", _future_meta(cron="0 9 * * *"))

    sched.print_scheduled_prompt_jobs()

    out = capsys.readouterr().out
    assert "sched_list_test" in out
    assert "run_scheduled_prompt" in out
    assert "metadata.json" in out
    assert '"channel_id": "C1"' in out
    assert "prompt.txt" in out
    assert "Check thread." in out
    assert sched._scheduler is None  # noqa: SLF001


def test_print_scheduled_prompt_jobs_empty(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sched, "scheduled_prompts_root", lambda: tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)

    sched.print_scheduled_prompt_jobs()

    assert "(no scheduled prompt jobs)" in capsys.readouterr().out
    assert sched._scheduler is None  # noqa: SLF001


@patch("common.tools.prompt_scheduler.prompt_scheduler.BackgroundScheduler")
def test_sequential_executor_config(mock_bs):
    sched.shutdown_scheduler()
    sched._scheduler = None  # noqa: SLF001
    mock_inst = MagicMock()
    mock_bs.return_value = mock_inst
    sched.start_scheduler()
    mock_bs.assert_called_once()
    call_kw = mock_bs.call_args[1]
    assert call_kw["job_defaults"]["max_instances"] == 1
    assert "default" in call_kw["executors"]
