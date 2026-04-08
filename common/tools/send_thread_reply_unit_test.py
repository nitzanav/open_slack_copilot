from unittest.mock import patch

import pytest

import common.tools.send_thread_reply  # noqa: F401 — registers tool
from common.slack.slack_bot import tool_confirmation as tc
from common.tools.copilot_tool import get_copilot_tool, get_tool_confirmation_spec


def test_tool_registered():
    assert get_copilot_tool("send_thread_reply") is not None
    assert get_tool_confirmation_spec("send_thread_reply") is not None


def test_execute_after_confirm_posts():
    tool = get_copilot_tool("send_thread_reply")
    assert tool and tool.execute_after_confirm
    with patch("common.tools.send_thread_reply.slack_api") as api:
        out = tool.execute_after_confirm(
            "hello",
            {"channel_id": "C1", "thread_ts": "1.0"},
        )
    assert "Posted" in out
    api.post_thread_message.assert_called_once_with("C1", "1.0", "hello")


def test_handle_confirm_action_send_thread_reply():
    spec = get_tool_confirmation_spec("send_thread_reply")
    assert spec is not None
    payload = {
        "channel_id": "C1",
        "thread_ts": "9.0",
        "prepare_user_id": "U_PREP",
        "context_kind": "thread",
    }
    blocks = tc._build_confirmation_blocks(
        "send_thread_reply", spec, "body text", payload,
    )
    actions = blocks[-1]["elements"]
    confirm_value = next(
        e["value"] for e in actions if e["action_id"] == tc.ACTION_TOOL_CONFIRM
    )
    body = {
        "user": {"id": "U_CLICKER"},
        "channel": {"id": "C1"},
        "actions": [{"value": confirm_value}],
        "message": {"blocks": blocks, "thread_ts": "9.0"},
    }
    with patch("common.tools.send_thread_reply.slack_api") as api:
        result = tc.handle_confirm_action(body)
        assert "Posted" in result
        api.post_thread_message.assert_called_once_with("C1", "9.0", "body text")
