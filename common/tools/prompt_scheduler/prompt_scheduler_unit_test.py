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


@patch("common.tools.prompt_scheduler.prompt_scheduler.prepare_draft")
@patch("common.tools.prompt_scheduler.prompt_scheduler.slack_api")
def test_run_calls_prepare_draft_with_prompt(mock_slack, mock_draft, tmp_path, monkeypatch):
    monkeypatch.setattr(sched, "scheduled_prompts_root", lambda: tmp_path)
    prompt_text = "Remind everyone about the deadline."
    _write_job(tmp_path, "sched_ok", _future_meta(), prompt=prompt_text)
    mock_draft.return_value = "Draft output"

    sched.run_scheduled_prompt("sched_ok")

    mock_draft.assert_called_once()
    call_kw = mock_draft.call_args
    assert call_kw[0] == ("C1", "T1", "U1")
    assert call_kw[1]["user_text"] == prompt_text
    from common.tools.send_slack_pm import SEND_SLACK_PM_TOOL
    assert call_kw[1]["tools"] == [SEND_SLACK_PM_TOOL]


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


@patch("common.tools.prompt_scheduler.prompt_scheduler.prepare_draft")
@patch("common.tools.prompt_scheduler.prompt_scheduler.remove_job")
@patch("common.tools.prompt_scheduler.prompt_scheduler.slack_api")
def test_thread_inaccessible_removes_job(mock_slack, mock_remove, mock_draft, tmp_path, monkeypatch):
    monkeypatch.setattr(sched, "scheduled_prompts_root", lambda: tmp_path)
    _write_job(tmp_path, "sched_bad", _future_meta())
    from common.slack.copilot_pipeline import ThreadFetchError
    mock_draft.side_effect = ThreadFetchError("gone")

    sched.run_scheduled_prompt("sched_bad")

    mock_remove.assert_called_once()


@patch("common.tools.prompt_scheduler.prompt_scheduler.prepare_draft")
@patch("common.tools.prompt_scheduler.prompt_scheduler.slack_api")
def test_result_sent_to_owner(mock_slack, mock_draft, tmp_path, monkeypatch):
    monkeypatch.setattr(sched, "scheduled_prompts_root", lambda: tmp_path)
    _write_job(tmp_path, "sched_owner", _future_meta())
    mock_draft.return_value = "Here is the draft"
    monkeypatch.setattr(sched, "_owner_id", lambda: "UOWNER")

    sched.run_scheduled_prompt("sched_owner")

    mock_slack.send_ephemeral.assert_called_once_with("C1", "T1", "UOWNER", "Here is the draft")


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
