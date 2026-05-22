import json
from unittest.mock import MagicMock, patch

import pytest

import common.tools.send_dm_as_app  # noqa: F401 — registers tool + confirmation spec
import common.tools.send_thread_reply_on_behalf_of_requester  # noqa: F401 — registers tool + confirmation spec
from common.skill_runs import skill_runs
from common.slack.slack_bot import tool_confirmation as tc
from common.tools.copilot_tool import ToolConfirmationSpec, get_tool_confirmation_spec
from common.tools.react_context import react_invocation_context


@pytest.fixture
def isolated_data_root(tmp_path):
    from config.config import settings
    settings.set("data_layer.root", str(tmp_path))
    yield tmp_path


def _sample_blocks(text: str, payload: dict | None = None, row_key: str = "R1") -> list[dict]:
    spec = get_tool_confirmation_spec("send_dm_as_app")
    assert spec is not None
    p = payload or {
        "target_user_id": "U_TARGET",
        "channel_id": "C1",
        "thread_ts": "1.0",
        "prepare_user_id": "U_PREP",
    }
    return tc._build_confirmation_blocks("send_dm_as_app", spec, text, p, row_key)


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
            tool_name, spec, "hello", payload, "R1",
        )
        actions = blocks[-1]["elements"]
        primary = next(
            e for e in actions if e["action_id"] == tc.ACTION_TOOL_CONFIRM
        )
        assert primary["text"]["text"] == label


def test_actions_block_has_thumbs_up_button():
    blocks = _sample_blocks("hi")
    actions = blocks[-1]["elements"]
    action_ids = [e["action_id"] for e in actions]
    assert tc.ACTION_TOOL_THUMBS_UP in action_ids
    assert tc.ACTION_TOOL_REVISE in action_ids
    assert tc.ACTION_TOOL_CONFIRM in action_ids
    thumbs = next(e for e in actions if e["action_id"] == tc.ACTION_TOOL_THUMBS_UP)
    assert thumbs["value"] == "R1"


def test_action_buttons_carry_conversation_or_row_key():
    blocks = _sample_blocks("hi", row_key="thread_ts__action_ts")
    for e in blocks[-1]["elements"]:
        assert e["value"] == "thread_ts__action_ts"


def test_body_blocks_use_mrkdwn_for_mentions():
    blocks = _sample_blocks("Hi <@U0ALHV1GDDK>, try make run")
    body = next(b for b in blocks if str(b.get("block_id", "")).startswith(tc.BLOCK_BODY_PREFIX))
    assert (body.get("text") or {}).get("type") == "mrkdwn"
    assert "<@U0ALHV1GDDK>" in (body.get("text") or {}).get("text", "")


def test_build_blocks_rejects_overflow():
    spec = get_tool_confirmation_spec("send_dm_as_app")
    assert spec is not None
    too_long = "m" * (tc._MAX_BODY_BLOCKS * tc._PLAIN_CHUNK + 1)
    with pytest.raises(ValueError, match="too long"):
        tc._build_confirmation_blocks(
            "send_dm_as_app", spec, too_long, {"target_user_id": "U1"}, "R1",
        )


def test_queue_tool_confirmation_persists_row_and_uses_row_key(isolated_data_root):
    from common.conversations import conversations as conv_mod

    payload = {
        "target_user_id": "U_RECIPIENT",
        "channel_id": "C1",
        "thread_ts": "1.0",
        "prepare_user_id": "U_PREP",
    }
    cid = conv_mod.make_conversation_id()
    with patch("common.slack.slack_bot.tool_confirmation.copilot_user_notify") as notify, \
         react_invocation_context(
            "C1", "1.0", "U_PREP",
            skill_id="reply/draft_thread_reply",
            action_ts="2026-05-10T00:00:00+00:00",
            conversation_id=cid,
         ):
        out = tc.queue_tool_confirmation(
            tool_name="send_dm_as_app",
            text_content="hello",
            payload=payload,
            channel_id="C1",
            thread_ts="1.0",
            requester_user_id="U_PREP",
        )
    assert out == "Tool confirmation requested"
    notify.notify_confirmation_blocks.assert_called_once()
    blocks = notify.notify_confirmation_blocks.call_args[0][4]
    actions = blocks[-1]["elements"]
    button_value = actions[0]["value"]
    assert button_value == cid
    row = skill_runs.get(skill_runs._row_key("1.0", "2026-05-10T00:00:00+00:00"))
    assert row is not None
    assert row.get("conversation_id") == cid
    assert row["tool_name"] == "send_dm_as_app"
    assert row["text"] == "hello"
    assert row["payload"]["target_user_id"] == "U_RECIPIENT"
    assert row["skill_id"] == "reply/draft_thread_reply"


def test_handle_confirm_action_loads_from_skill_runs(isolated_data_root):
    payload = {
        "target_user_id": "U_RECIPIENT",
        "channel_id": "C1",
        "thread_ts": "1.0",
        "prepare_user_id": "U_PREP",
    }
    key = skill_runs.init_run(
        skill_id="reply/x", channel_id="C1", thread_ts="1.0",
        action_ts="A1", requester_user_id="U_PREP",
        tool_name="send_dm_as_app", payload=payload, text="draft body",
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
        api.send_dm.assert_called_once_with("U_RECIPIENT", "draft body")


def test_handle_confirm_action_missing_row(isolated_data_root):
    body = {
        "user": {"id": "U_CLICKER"},
        "channel": {"id": "C1"},
        "actions": [{"value": "missing_key"}],
        "message": {},
    }
    out = tc.handle_confirm_action(body)
    assert "expired" in out.lower()


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


def test_queue_tool_confirmation_requires_action_ts(isolated_data_root):
    with patch("common.slack.slack_bot.tool_confirmation.copilot_user_notify"), \
         react_invocation_context("C1", "1.0", "U1"):  # no action_ts
        out = tc.queue_tool_confirmation(
            tool_name="send_dm_as_app",
            text_content="hi",
            payload={"target_user_id": "U1"},
            channel_id="C1",
            thread_ts="1.0",
            requester_user_id="U1",
        )
    assert "action_ts" in out


def test_extra_params_section_in_blocks():
    spec = ToolConfirmationSpec(
        text_param_key="body",
        ephemeral_notification_text="x",
        confirmation_header_markdown="*Hdr*",
        confirm_button_text="Send",
        extra_param_keys_to_display=("issue_key",),
    )
    blocks = tc._build_confirmation_blocks(
        "fake_tool", spec, "hello", {"issue_key": "FOO-1", "body": "hello"}, "R1",
    )
    extra = next(b for b in blocks if b.get("block_id") == "tool_confirm_extra_params")
    assert "FOO-1" in (extra.get("text") or {}).get("text", "")


def test_handle_revise_open_modal_uses_row_key(isolated_data_root):
    payload = {
        "target_user_id": "U1",
        "channel_id": "C1",
        "thread_ts": "1.0",
        "prepare_user_id": "U_PREP",
    }
    key = skill_runs.init_run(
        skill_id="reply/x", channel_id="C1", thread_ts="1.0",
        action_ts="A1", requester_user_id="U_PREP",
        tool_name="send_dm_as_app", payload=payload, text="draft line",
    )
    body = {
        "trigger_id": "T",
        "user": {"id": "U_PREP"},
        "channel": {"id": "C1"},
        "message": {},
        "actions": [{"value": key}],
    }
    client = MagicMock()
    tc.handle_revise_open_modal(body, client)
    client.views_open.assert_called_once()
    call_kw = client.views_open.call_args[1]
    assert call_kw["trigger_id"] == "T"
    view = call_kw["view"]
    assert view["callback_id"] == tc.CALLBACK_TOOL_CONFIRM_REVISE_MODAL
    assert view["private_metadata"] == key


def test_handle_thumbs_up_records_reference(isolated_data_root, tmp_path):
    skill_id = "reply/foo"
    key = skill_runs.init_run(
        skill_id=skill_id, channel_id="C1", thread_ts="T1",
        action_ts="A1", requester_user_id="U_PREP",
        tool_name="send_dm_as_app", payload={}, text="hi",
    )
    body = {
        "user": {"id": "U_PREP"},
        "channel": {"id": "C1"},
        "actions": [{"value": key}],
        "message": {},
    }
    with patch(
        "common.skill_thumbs_up.skill_thumbs_up.SKILLS_ROOT",
        tmp_path / "skills",
    ):
        result = tc.handle_thumbs_up(body)
        from common.skill_thumbs_up import skill_thumbs_up
        refs = skill_thumbs_up.recent_references(skill_id)
        assert refs == [{"thread_ts": "T1", "action_ts": "A1"}]
    assert "saved as an example" in result
    assert skill_id in result


def test_handle_thumbs_up_missing_row(isolated_data_root):
    body = {
        "user": {"id": "U_PREP"},
        "channel": {"id": "C1"},
        "actions": [{"value": "no_such_key"}],
        "message": {},
    }
    result = tc.handle_thumbs_up(body)
    assert "expired" in result.lower()


def test_handle_thumbs_up_missing_skill_id(isolated_data_root):
    key = skill_runs.init_run(
        skill_id=None, channel_id="C1", thread_ts="T1",
        action_ts="A1", requester_user_id="U_PREP",
        tool_name="send_dm_as_app", payload={}, text="hi",
    )
    body = {
        "user": {"id": "U_PREP"},
        "channel": {"id": "C1"},
        "actions": [{"value": key}],
        "message": {},
    }
    result = tc.handle_thumbs_up(body)
    assert "thumbs-up not saved" in result.lower()
