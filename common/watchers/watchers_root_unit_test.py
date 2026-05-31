import json
from unittest.mock import patch

from common.watchers import watchers_root as wr
from common.watchers.watcher_config import SUPPORTED_TRIGGER


def _good_dict() -> dict:
    return {
        "trigger": SUPPORTED_TRIGGER,
        "requester_user_id": "U1",
        "channel_id": "C1",
        "run_skill_id": "summarize_thread",
        "thread_started_after": 100,
        "skill_didnt_run_for": 10,
        "thread_had_more_than_x_messages_since_last_skill_run": 1,
        "thread_quiet_for_x_seconds": 60,
    }


def test_load_all_returns_empty_when_root_missing(tmp_path):
    with patch.object(wr, "watchers_root", return_value=tmp_path / "missing"):
        assert wr.load_all() == []


def test_load_all_returns_valid_and_skips_invalid(tmp_path):
    (tmp_path / "alpha.json").write_text(json.dumps(_good_dict()))
    (tmp_path / "beta.json").write_text(json.dumps(_good_dict() | {"trigger": "x"}))
    (tmp_path / "broken.json").write_text("{not json")
    (tmp_path / "ignored.txt").write_text("nope")
    with patch.object(wr, "watchers_root", return_value=tmp_path):
        cfgs = wr.load_all()
        assert [c.name for c in cfgs] == ["alpha"]
        assert cfgs[0].channel_id == "C1"
