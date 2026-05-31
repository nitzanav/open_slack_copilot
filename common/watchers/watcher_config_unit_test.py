import pytest

from common.watchers.watcher_config import (
    SUPPORTED_TRIGGER,
    WatcherConfig,
    validate_watcher_config,
)


def _good_raw() -> dict:
    return {
        "trigger": SUPPORTED_TRIGGER,
        "requester_user_id": "U1",
        "channel_id": "C1",
        "run_skill_id": "summarize_thread",
        "thread_started_after": 604800,
        "skill_didnt_run_for": 7200,
        "thread_had_more_than_x_messages_since_last_skill_run": 3,
        "thread_quiet_for_x_seconds": 3600,
    }


def test_validate_ok():
    cfg = validate_watcher_config(_good_raw(), name="summarize_active")
    assert isinstance(cfg, WatcherConfig)
    assert cfg.name == "summarize_active"
    assert cfg.trigger == SUPPORTED_TRIGGER
    assert cfg.requester_user_id == "U1"
    assert cfg.run_skill_id == "summarize_thread"
    assert cfg.thread_started_after == 604800
    assert cfg.thread_quiet_for_x_seconds == 3600


def test_rejects_other_trigger():
    raw = _good_raw() | {"trigger": "channel_message"}
    with pytest.raises(ValueError, match="trigger"):
        validate_watcher_config(raw, name="x")


def test_rejects_missing_channel_id():
    raw = _good_raw() | {"channel_id": ""}
    with pytest.raises(ValueError, match="channel_id"):
        validate_watcher_config(raw, name="x")


def test_rejects_unsafe_skill_id():
    raw = _good_raw() | {"run_skill_id": "../etc"}
    with pytest.raises(ValueError, match="run_skill_id"):
        validate_watcher_config(raw, name="x")


def test_rejects_negative_int():
    raw = _good_raw() | {"thread_started_after": -1}
    with pytest.raises(ValueError, match="thread_started_after"):
        validate_watcher_config(raw, name="x")


def test_rejects_non_int():
    raw = _good_raw() | {"skill_didnt_run_for": "7200"}
    with pytest.raises(ValueError, match="skill_didnt_run_for"):
        validate_watcher_config(raw, name="x")


def test_rejects_empty_name():
    with pytest.raises(ValueError, match="name"):
        validate_watcher_config(_good_raw(), name="")
