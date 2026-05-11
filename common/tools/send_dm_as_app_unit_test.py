from unittest.mock import patch

import pytest

import common.tools.send_dm_as_app  # noqa: F401 — registers tool
from common.skill_runs import skill_runs
from common.slack.slack_bot import tool_confirmation as tc
from common.tools.copilot_tool import get_copilot_tool, get_tool_confirmation_spec
from common.tools.send_dm_as_app import SEND_DM_AS_APP, SEND_DM_AS_APP_TOOL


@pytest.fixture
def isolated_data_root(tmp_path):
    from config.config import settings
    settings.set("data_layer.root", str(tmp_path))
    yield tmp_path


def test_tool_definition_schema():
    assert SEND_DM_AS_APP_TOOL["type"] == "function"
    assert SEND_DM_AS_APP_TOOL["function"]["name"] == "send_dm_as_app"
    params = SEND_DM_AS_APP_TOOL["function"]["parameters"]
    assert set(params["required"]) == {"user", "message"}


def test_tool_registered():
    assert get_copilot_tool("send_dm_as_app") is not None
    assert get_tool_confirmation_spec("send_dm_as_app") is not None


def test_execute_after_confirm_sends():
    tool = get_copilot_tool("send_dm_as_app")
    assert tool and tool.execute_after_confirm
    with patch("common.tools.send_dm_as_app.slack_api") as api:
        out = tool.execute_after_confirm(
            "body",
            {
                "target_user_id": "U_T",
                "channel_id": "C1",
                "thread_ts": "1.0",
                "prepare_user_id": "U_PREP",
            },
        )
    assert out == "Sent."
    api.send_dm.assert_called_once_with("U_T", "body")


def test_handle_confirm_action_send_dm_as_app(isolated_data_root):
    payload = {
        "target_user_id": "U_T",
        "channel_id": "C1",
        "thread_ts": "9.0",
        "prepare_user_id": "U_PREP",
        "context_kind": "thread",
    }
    key = skill_runs.init_run(
        skill_id="reply/x", channel_id="C1", thread_ts="9.0",
        action_ts="A1", requester_user_id="U_PREP",
        tool_name="send_dm_as_app", payload=payload, text="hi",
    )
    body = {
        "user": {"id": "U_CLICKER"},
        "channel": {"id": "C1"},
        "actions": [{"value": key}],
        "message": {},
    }
    with patch("common.tools.send_dm_as_app.slack_api") as api:
        result = tc.handle_confirm_action(body)
        assert result == "Sent."
        api.send_dm.assert_called_once_with("U_T", "hi")


def test_handle_requires_invocation_context():
    import json as _json

    out = _json.loads(SEND_DM_AS_APP.handle(_json.dumps({"user": "U0123456789", "message": "hi"})))
    assert "error" in out
