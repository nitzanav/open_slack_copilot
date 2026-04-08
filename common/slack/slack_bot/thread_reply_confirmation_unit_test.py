import json

import pytest

from common.slack.slack_bot.thread_reply_confirmation import (
    BLOCK_INCLUDE_REPLY,
    BLOCK_REVISE_INPUT,
    ACTION_INCLUDE_REPLY,
    ACTION_REVISE_TEXT,
    ReviseError,
    _BUTTON_VALUE_LIMIT,
    _build_metadata_value,
    _build_private_metadata,
    _build_revise_modal_view,
    _checkbox_is_selected,
    _compose_revise_user_text,
    build_reply_confirmation_blocks,
    parse_reply_text_from_blocks,
)


def test_parse_reply_joins_chunks():
    blocks = [
        {"block_id": "reply_body_1", "text": {"type": "plain_text", "text": "second"}},
        {"block_id": "reply_body_0", "text": {"type": "plain_text", "text": "first"}},
    ]
    assert parse_reply_text_from_blocks(blocks) == "firstsecond"


def test_parse_reply_empty_raises():
    with pytest.raises(ReviseError):
        parse_reply_text_from_blocks([])


def test_build_blocks_contains_revise_action_with_metadata():
    meta = json.dumps(
        {
            "channel_id": "C1",
            "anchor_ts": "T1",
            "prepare_user_id": "U1",
            "auth_user_id": "U1",
            "context_kind": "thread",
        },
        separators=(",", ":"),
    )
    blocks = build_reply_confirmation_blocks("Hello reply", meta)
    actions = [b for b in blocks if b.get("type") == "actions"][0]
    btn = actions["elements"][0]
    assert btn["action_id"] == "reply_confirm_revise"
    assert json.loads(btn["value"])["channel_id"] == "C1"


class TestBuildMetadataValue:
    def test_includes_reply_text(self):
        result = _build_metadata_value(
            channel_id="C1",
            anchor_ts="T1",
            prepare_user_id="U1",
            auth_user_id="U1",
            context_kind="thread",
            reply_text="Hello reply",
        )
        parsed = json.loads(result)
        assert parsed["reply_text"] == "Hello reply"
        assert parsed["channel_id"] == "C1"

    def test_truncates_long_reply_text(self):
        result = _build_metadata_value(
            channel_id="C1",
            anchor_ts="T1",
            prepare_user_id="U1",
            auth_user_id="U1",
            context_kind="thread",
            reply_text="x" * 5000,
        )
        assert len(result) <= _BUTTON_VALUE_LIMIT
        parsed = json.loads(result)
        assert parsed["reply_text"].endswith("...")
        assert parsed["channel_id"] == "C1"

    def test_no_reply_text_omits_key(self):
        result = _build_metadata_value(
            channel_id="C1",
            anchor_ts="T1",
            prepare_user_id="U1",
            auth_user_id="U1",
            context_kind="thread",
        )
        parsed = json.loads(result)
        assert "reply_text" not in parsed


class TestBuildReviseModalView:
    def _meta_json(self) -> str:
        return json.dumps(
            {
                "channel_id": "C1",
                "anchor_ts": "T1",
                "prepare_user_id": "U1",
                "auth_user_id": "U1",
                "context_kind": "thread",
            },
            separators=(",", ":"),
        )

    def test_instruction_input_has_placeholder_no_initial_value(self):
        view = _build_revise_modal_view("reply text", self._meta_json())
        instruction_block = view["blocks"][0]
        el = instruction_block["element"]
        assert el["type"] == "plain_text_input"
        assert "initial_value" not in el
        assert el["placeholder"]["text"] == "e.g. make it shorter, more formal..."

    def test_checkbox_block_present_and_initially_selected(self):
        view = _build_revise_modal_view("reply text", self._meta_json())
        cb_block = view["blocks"][1]
        el = cb_block["element"]
        assert el["type"] == "checkboxes"
        assert el["action_id"] == ACTION_INCLUDE_REPLY
        assert len(el["initial_options"]) == 1
        assert el["initial_options"][0]["value"] == "include"

    def test_reply_text_stored_in_private_metadata(self):
        view = _build_revise_modal_view("my reply", self._meta_json())
        pm = json.loads(view["private_metadata"])
        assert pm["reply_text"] == "my reply"
        assert pm["channel_id"] == "C1"

    def test_long_reply_text_truncated_in_private_metadata(self):
        long_text = "x" * 5000
        view = _build_revise_modal_view(long_text, self._meta_json())
        pm = json.loads(view["private_metadata"])
        assert len(view["private_metadata"]) <= 3000
        assert pm["reply_text"].endswith("...")
        assert pm["channel_id"] == "C1"


class TestBuildPrivateMetadata:
    def test_short_reply_text_preserved(self):
        meta_json = json.dumps({"a": "b"}, separators=(",", ":"))
        result = _build_private_metadata(meta_json, "hello")
        parsed = json.loads(result)
        assert parsed["reply_text"] == "hello"
        assert parsed["a"] == "b"

    def test_exceeding_limit_truncates_reply_text(self):
        meta_json = json.dumps({"k": "v"}, separators=(",", ":"))
        result = _build_private_metadata(meta_json, "z" * 5000)
        assert len(result) <= 3000
        parsed = json.loads(result)
        assert parsed["reply_text"].endswith("...")


class TestCheckboxIsSelected:
    def test_selected(self):
        values = {
            BLOCK_INCLUDE_REPLY: {
                ACTION_INCLUDE_REPLY: {
                    "selected_options": [{"value": "include"}],
                },
            },
        }
        assert _checkbox_is_selected(values) is True

    def test_not_selected(self):
        values = {
            BLOCK_INCLUDE_REPLY: {
                ACTION_INCLUDE_REPLY: {
                    "selected_options": [],
                },
            },
        }
        assert _checkbox_is_selected(values) is False

    def test_missing_block(self):
        assert _checkbox_is_selected({}) is False


class TestComposeReviseUserText:
    def test_with_reply_included(self):
        result = _compose_revise_user_text("be shorter", "old reply", True)
        assert "The original reply suggestion was:\nold reply" in result
        assert "The user requested a revision with this instruction:\nbe shorter" in result

    def test_without_reply(self):
        assert _compose_revise_user_text("be shorter", "old reply", False) == "be shorter"

    def test_include_but_empty_reply(self):
        assert _compose_revise_user_text("be shorter", "", True) == "be shorter"
