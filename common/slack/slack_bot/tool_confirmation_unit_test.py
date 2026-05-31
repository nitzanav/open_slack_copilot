import json
from unittest.mock import MagicMock, patch

import pytest

import common.tools.send_dm_as_app  # noqa: F401 — registers tool + confirmation spec
import common.tools.send_thread_reply_on_behalf_of_requester  # noqa: F401 — registers tool + confirmation spec
from common.slack.slack_bot import tool_confirmation as tc
from common.tools.copilot_tool import ToolConfirmationSpec, get_tool_confirmation_spec


def _sample_blocks(text: str, payload: dict | None = None) -> list[dict]:
    spec = get_tool_confirmation_spec("send_dm_as_app")
    assert spec is not None
    p = payload or {
        "target_user_id": "U_TARGET",
        "channel_id": "C1",
        "thread_ts": "1.0",
        "prepare_user_id": "U_PREP",
    }
    return tc._build_confirmation_blocks("send_dm_as_app", spec, text, p)


def test_ephemeral_thread_ts_prefers_message_then_container():
    thread_root = "1778357030.363219"
    assert (
        tc._ephemeral_thread_ts(
            {
                "message": {"thread_ts": thread_root},
                "container": {"thread_ts": "other"},
            },
        )
        == thread_root
    )
    assert (
        tc._ephemeral_thread_ts(
            {
                "message": {"ts": "1778357039.000400"},
                "container": {"thread_ts": thread_root},
            },
        )
        == thread_root
    )


def test_confirm_primary_button_uses_spec_label():
    for tool_name, label, payload in (
        (
            "send_thread_reply_on_behalf_of_requester",
            "Send thread reply",
            {"channel_id": "C1", "thread_ts": "1.0", "prepare_user_id": "U1"},
        ),
        (
            "send_dm_as_app",
            "Send DM",
            {
                "target_user_id": "U_TARGET",
                "channel_id": "C1",
                "thread_ts": "1.0",
                "prepare_user_id": "U_PREP",
            },
        ),
    ):
        spec = get_tool_confirmation_spec(tool_name)
        assert spec is not None
        assert spec.confirm_button_text == label
        blocks = tc._build_confirmation_blocks(
            tool_name, spec, "hello", payload,
        )
        actions = blocks[-1]["elements"]
        primary = next(
            e for e in actions if e["action_id"] == tc.ACTION_TOOL_CONFIRM
        )
        assert primary["text"]["text"] == label


def test_body_blocks_use_mrkdwn_for_mentions():
    blocks = _sample_blocks("Hi <@U0ALHV1GDDK>, try make run")
    body = next(b for b in blocks if str(b.get("block_id", "")).startswith(tc.BLOCK_BODY_PREFIX))
    assert (body.get("text") or {}).get("type") == "mrkdwn"
    assert "<@U0ALHV1GDDK>" in (body.get("text") or {}).get("text", "")


def test_body_blocks_convert_github_bold_to_slack_mrkdwn():
    blocks = _sample_blocks("**Merchant name:** acme")
    body = next(b for b in blocks if str(b.get("block_id", "")).startswith(tc.BLOCK_BODY_PREFIX))
    assert (body.get("text") or {}).get("text") == "*Merchant name:* acme"


def test_build_blocks_rejects_overflow():
    spec = get_tool_confirmation_spec("send_dm_as_app")
    assert spec is not None
    too_long = "m" * (tc._MAX_BODY_BLOCKS * tc._PLAIN_CHUNK + 1)
    with pytest.raises(ValueError, match="too long"):
        tc._build_confirmation_blocks(
            "send_dm_as_app", spec, too_long, {"target_user_id": "U1"}
        )


def test_handle_confirm_action_uses_draft_ref_when_blocks_missing():
    payload = {
        "target_user_id": "U_RECIPIENT",
        "channel_id": "C1",
        "thread_ts": "1.0",
        "prepare_user_id": "U_PREP",
    }
    blocks = _sample_blocks("draft body", payload)
    actions = blocks[-1]["elements"]
    confirm_value = next(
        e["value"] for e in actions if e["action_id"] == tc.ACTION_TOOL_CONFIRM
    )
    meta = json.loads(confirm_value)
    assert "draft_ref" in meta
    body = {
        "user": {"id": "U_CLICKER"},
        "channel": {"id": "C1"},
        "actions": [{"value": confirm_value}],
        "message": {"blocks": []},
    }
    with patch("common.tools.send_dm_as_app.slack_api") as api:
        result = tc.handle_confirm_action(body)
        assert result == "Sent."
        api.send_dm.assert_called_once_with("U_RECIPIENT", "draft body")


def test_handle_confirm_action_signals_watchers():
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
    with patch("common.tools.send_dm_as_app.slack_api"), \
         patch("common.watchers.watchers.dispatch_watchers_async") as dispatch:
        tc.handle_confirm_action(body)
        dispatch.assert_called_once_with("any_tool_confirmation")


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
    with patch("common.tools.send_dm_as_app.slack_api") as api:
        result = tc.handle_confirm_action(body)
        assert result == "Sent."
        api.send_dm.assert_called_once_with("U_RECIPIENT", "body text")


def test_queue_tool_confirmation_requires_requester():
    with patch("common.slack.slack_bot.tool_confirmation.slack_api"):
        out = tc.queue_tool_confirmation(
            tool_name="send_dm_as_app",
            text_content="hi",
            payload={"target_user_id": "U1"},
            channel_id="C",
            thread_ts=None,
            requester_user_id="",
        )
        assert "requester_user_id" in out


def test_extra_params_section_in_blocks():
    spec = ToolConfirmationSpec(
        text_param_key="body",
        ephemeral_notification_text="x",
        confirmation_header_markdown="*Hdr*",
        confirm_button_text="Send",
        extra_param_keys_to_display=("issue_key",),
    )
    blocks = tc._build_confirmation_blocks(
        "fake_tool", spec, "hello", {"issue_key": "FOO-1", "body": "hello"}
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
