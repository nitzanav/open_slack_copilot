import json
from unittest.mock import patch

import pytest

from common.tools.prompt_scheduler import prompt_scheduler as sched


@pytest.fixture(autouse=True)
def _stop_scheduler_after():
    yield
    sched.shutdown_scheduler()
    sched._scheduler = None  # noqa: SLF001


@patch("common.tools.prompt_scheduler.prompt_scheduler.register_job_from_disk")
def test_reload_registers_each_job(mock_register, tmp_path, monkeypatch):
    monkeypatch.setattr(sched, "scheduled_prompts_root", lambda: tmp_path)
    for name in ("sched_a", "sched_b"):
        d = tmp_path / name
        d.mkdir()
        (d / "metadata.json").write_text(json.dumps({"cron": "0 9 * * *"}))
        (d / "prompt.txt").write_text("check thread")

    sched.reload_jobs_from_disk()

    assert mock_register.call_count == 2
    ids = {c[0][0] for c in mock_register.call_args_list}
    assert ids == {"sched_a", "sched_b"}
