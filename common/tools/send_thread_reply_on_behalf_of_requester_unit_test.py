from unittest.mock import patch

import pytest

import common.tools.send_thread_reply_on_behalf_of_requester  # noqa: F401 — registers tool
from common.skill_runs import skill_runs
from common.slack.slack_api.errors import OAuthNotConnectedError
from common.slack.slack_bot import tool_confirmation as tc
from common.tools.copilot_tool import get_copilot_tool, get_tool_confirmation_spec


@pytest.fixture
def isolated_data_root(tmp_path):
    from config.config import settings
    settings.set("data_layer.root", str(tmp_path))
    yield tmp_path


def test_tool_registered():
    assert get_copilot_tool("send_thread_reply_on_behalf_of_requester") is not None
    assert get_tool_confirmation_spec("send_thread_reply_on_behalf_of_requester") is not None


def test_execute_after_confirm_posts():
    tool = get_copilot_tool("send_thread_reply_on_behalf_of_requester")
    assert tool and tool.execute_after_confirm
    with patch(
        "common.tools.send_thread_reply_on_behalf_of_requester.slack_api"
    ) as api:
        out = tool.execute_after_confirm(
            "hello",
            {
                "channel_id": "C1",
                "thread_ts": "1.0",
                "prepare_user_id": "U_REQ",
            },
        )
    assert "Posted" in out
    api.post_thread_message_on_behalf_of_requester.assert_called_once_with(
        "C1", "1.0", "hello", "U_REQ",
    )


def test_execute_after_confirm_oauth_missing_message():
    tool = get_copilot_tool("send_thread_reply_on_behalf_of_requester")
    assert tool and tool.execute_after_confirm
    with patch(
        "common.tools.send_thread_reply_on_behalf_of_requester.slack_api"
    ) as api:
        api.post_thread_message_on_behalf_of_requester.side_effect = (
            OAuthNotConnectedError("U_REQ")
        )
        out = tool.execute_after_confirm(
            "hello",
            {
                "channel_id": "C1",
                "thread_ts": "1.0",
                "prepare_user_id": "U_REQ",
            },
        )
    assert "No OAuth" in out


def test_handle_confirm_action_send_thread_reply_on_behalf_of_requester(isolated_data_root):
    payload = {
        "channel_id": "C1",
        "thread_ts": "9.0",
        "prepare_user_id": "U_PREP",
        "context_kind": "thread",
    }
    key = skill_runs.init_run(
        skill_id="reply/x", channel_id="C1", thread_ts="9.0",
        action_ts="A1", requester_user_id="U_PREP",
        tool_name="send_thread_reply_on_behalf_of_requester",
        payload=payload, text="body text",
    )
    body = {
        "user": {"id": "U_CLICKER"},
        "channel": {"id": "C1"},
        "actions": [{"value": key}],
        "message": {},
    }
    with patch(
        "common.tools.send_thread_reply_on_behalf_of_requester.slack_api"
    ) as api:
        result = tc.handle_confirm_action(body)
        assert "Posted" in result
        api.post_thread_message_on_behalf_of_requester.assert_called_once_with(
            "C1", "9.0", "body text", "U_PREP",
        )
