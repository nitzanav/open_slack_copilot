import json
from pathlib import Path
from unittest.mock import patch

import pytest

from common.skill_runs import skill_runs


@pytest.fixture
def isolated_data_root(tmp_path, monkeypatch):
    """Point data_layer at a temp root for each test."""
    from config.config import settings
    settings.set("data_layer.root", str(tmp_path))
    yield tmp_path


def test_row_key_format():
    assert skill_runs._row_key("1.0", "2026-05-10T00:00:00+00:00") == "1.0__2026-05-10T00:00:00+00:00"


def test_init_run_writes_row(isolated_data_root):
    key = skill_runs.init_run(
        skill_id="x",
        channel_id="C1",
        thread_ts="1.0",
        action_ts="2026-05-10T00:00:00+00:00",
        requester_user_id="U1",
        tool_name="send_dm_as_app",
        payload={"target_user_id": "U2"},
        text="hello",
    )
    row = skill_runs.get(key)
    assert row is not None
    assert row["skill_id"] == "x"
    assert row["tool_name"] == "send_dm_as_app"
    assert row["payload"] == {"target_user_id": "U2"}
    assert skill_runs.get_text(key) == "hello"
    assert skill_runs.get_payload(key) == {"target_user_id": "U2"}
    assert skill_runs.get_skill_id(key) == "x"


def test_enrich_with_run_log_merges(isolated_data_root):
    key = skill_runs.init_run(
        skill_id="x", channel_id="C", thread_ts="1.0",
        action_ts="2026-05-10T00:00:00+00:00", requester_user_id="U1",
        tool_name="t", payload={}, text="t",
    )
    skill_runs.enrich_with_run_log(key, {"tool_trace": [{"name": "t", "result_preview": "ok"}]})
    row = skill_runs.get(key)
    assert row["run_log"]["tool_trace"][0]["name"] == "t"
    assert row["text"] == "t"


def test_enrich_with_run_log_missing_row_is_noop(isolated_data_root):
    skill_runs.enrich_with_run_log("nope", {"x": 1})
    assert skill_runs.get("nope") is None


def test_format_as_example_renders_essentials():
    row = {
        "skill_id": "x",
        "action_ts": "2026-05-10T00:00:00+00:00",
        "payload": {"user_text": "draft a reply"},
        "text": "Hi there.",
        "run_log": {"tool_trace": [{"name": "send_thread_reply_on_behalf_of_requester"}]},
    }
    out = skill_runs.format_as_example(row)
    assert "x" in out
    assert "draft a reply" in out
    assert "send_thread_reply_on_behalf_of_requester" in out
    assert "Hi there." in out


def test_init_run_returns_conversation_id_when_passed(isolated_data_root):
    ret = skill_runs.init_run(
        skill_id="x",
        channel_id="C1",
        thread_ts="1.0",
        action_ts="2026-05-10T00:00:00+00:00",
        requester_user_id="U1",
        tool_name="send_dm_as_app",
        payload={},
        text="hello",
        conversation_id="opaque-cid-123",
    )
    assert ret == "opaque-cid-123"
    row = skill_runs.get(skill_runs._row_key("1.0", "2026-05-10T00:00:00+00:00"))
    assert row is not None
    assert row.get("conversation_id") == "opaque-cid-123"


