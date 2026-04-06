from unittest.mock import MagicMock, patch

import pytest

from common.slack.slack_bot import tool_confirmation as tc


def _sample_blocks(text: str, payload: dict | None = None) -> list[dict]:
    spec = tc.get_tool_risk_spec("send_slack_pm")
    assert spec is not None
    p = payload or {
        "target_user_id": "U_TARGET",
        "channel_id": "C1",
        "thread_ts": "1.0",
        "prepare_user_id": "U_PREP",
    }
    return tc._build_confirmation_blocks(spec, text, p)


def test_parse_text_single_chunk():
    blocks = _sample_blocks("hello world")
    spec = tc.get_tool_risk_spec("send_slack_pm")
    assert spec is not None
    msg = tc.parse_text_from_confirmation_blocks(blocks, spec.text_param_key)
    assert msg == "hello world"


def test_parse_text_multichunk():
    long_text = "x" * 4500
    blocks = _sample_blocks(long_text)
    spec = tc.get_tool_risk_spec("send_slack_pm")
    assert spec is not None
    msg = tc.parse_text_from_confirmation_blocks(blocks, spec.text_param_key)
    assert msg == long_text


def test_build_blocks_rejects_overflow():
    spec = tc.get_tool_risk_spec("send_slack_pm")
    assert spec is not None
    too_long = "m" * (tc._MAX_BODY_BLOCKS * tc._PLAIN_CHUNK + 1)
    with pytest.raises(ValueError, match="too long"):
        tc._build_confirmation_blocks(spec, too_long, {"target_user_id": "U1"})


def test_handle_confirm_action_parses_and_sends():
    payload = {
        "target_user_id": "U_RECIPIENT",
        "channel_id": "C1",
        "thread_ts": "1.0",
        "prepare_user_id": "U_PREP",
    }
    blocks = _sample_blocks("body text", payload)
    actions = blocks[-1]["elements"]
    confirm_value = next(
        e["value"] for e in actions if e["action_id"] == tc.ACTION_TOOL_CONFIRM
    )
    body = {
        "user": {"id": "U_CLICKER"},
        "channel": {"id": "C1"},
        "actions": [{"value": confirm_value}],
        "message": {"blocks": blocks, "thread_ts": "1.0"},
    }
    with patch("common.slack.slack_bot.tool_confirmation.slack_api") as api:
        result = tc.handle_confirm_action(body)
        assert result == "Sent."
        api.send_dm.assert_called_once_with("U_RECIPIENT", "body text")


def test_queue_tool_confirmation_requires_requester():
    with patch("common.slack.slack_bot.tool_confirmation.slack_api"):
        out = tc.queue_tool_confirmation(
            tool_name="send_slack_pm",
            text_content="hi",
            payload={"target_user_id": "U1"},
            channel_id="C",
            thread_ts=None,
            requester_user_id="",
        )
        assert "requester_user_id" in out


def test_extra_params_section_in_blocks():
    from common.tools.tool_risk_defs import ToolRiskSpec

    spec = ToolRiskSpec(
        tool_name="fake_tool",
        text_param_key="body",
        ephemeral_notification_text="x",
        confirmation_header_markdown="*Hdr*",
        extra_param_keys_to_display=("issue_key",),
    )
    blocks = tc._build_confirmation_blocks(
        spec, "hello", {"issue_key": "FOO-1", "body": "hello"}
    )
    extra = next(b for b in blocks if b.get("block_id") == "tool_confirm_extra_params")
    assert "FOO-1" in (extra.get("text") or {}).get("text", "")


def test_handle_revise_open_modal():
    payload = {
        "target_user_id": "U1",
        "channel_id": "C1",
        "thread_ts": "1.0",
        "prepare_user_id": "U_PREP",
    }
    blocks = _sample_blocks("draft line", payload)
    actions = blocks[-1]["elements"]
    revise_value = next(
        e["value"] for e in actions if e["action_id"] == tc.ACTION_TOOL_REVISE
    )
    body = {
        "trigger_id": "T",
        "user": {"id": "U_PREP"},
        "channel": {"id": "C1"},
        "message": {"blocks": blocks},
        "actions": [{"value": revise_value}],
    }
    client = MagicMock()
    with patch.object(tc, "_build_tool_revise_modal_view", return_value={"type": "modal"}):
        tc.handle_revise_open_modal(body, client)
    client.views_open.assert_called_once()
    call_kw = client.views_open.call_args[1]
    assert call_kw["trigger_id"] == "T"
    assert call_kw["view"]["type"] == "modal"
