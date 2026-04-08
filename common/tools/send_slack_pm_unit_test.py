import json

from common.tools.send_slack_pm import SEND_SLACK_PM, SEND_SLACK_PM_TOOL


def test_tool_definition_schema():
    assert SEND_SLACK_PM_TOOL["type"] == "function"
    assert SEND_SLACK_PM_TOOL["function"]["name"] == "send_slack_pm"
    params = SEND_SLACK_PM_TOOL["function"]["parameters"]
    assert set(params["required"]) == {"user", "message"}


def test_handle_requires_invocation_context():
    out = json.loads(
        SEND_SLACK_PM.handle(json.dumps({"user": "U0123456789", "message": "hi"}))
    )
    assert "error" in out
