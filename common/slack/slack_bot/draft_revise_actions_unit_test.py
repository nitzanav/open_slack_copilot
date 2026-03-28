import json

import pytest

from common.slack.slack_bot.draft_revise_actions import (
    BLOCK_INCLUDE_DRAFT,
    BLOCK_REVISE_INPUT,
    ACTION_INCLUDE_DRAFT,
    ACTION_REVISE_TEXT,
    DraftReviseError,
    _build_private_metadata,
    _build_revise_modal_view,
    _checkbox_is_selected,
    _compose_revise_user_text,
    build_draft_revise_blocks,
    parse_draft_from_revise_blocks,
)


def test_parse_draft_joins_chunks():
    blocks = [
        {"block_id": "draft_body_1", "text": {"type": "plain_text", "text": "second"}},
        {"block_id": "draft_body_0", "text": {"type": "plain_text", "text": "first"}},
    ]
    assert parse_draft_from_revise_blocks(blocks) == "firstsecond"


def test_parse_draft_empty_raises():
    with pytest.raises(DraftReviseError):
        parse_draft_from_revise_blocks([])


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
    blocks = build_draft_revise_blocks("Hello draft", meta)
    actions = [b for b in blocks if b.get("type") == "actions"][0]
    btn = actions["elements"][0]
    assert btn["action_id"] == "draft_revise"
    assert json.loads(btn["value"])["channel_id"] == "C1"


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
        view = _build_revise_modal_view("draft text", self._meta_json())
        instruction_block = view["blocks"][0]
        el = instruction_block["element"]
        assert el["type"] == "plain_text_input"
        assert "initial_value" not in el
        assert el["placeholder"]["text"] == "e.g. make it shorter, more formal..."

    def test_checkbox_block_present_and_initially_selected(self):
        view = _build_revise_modal_view("draft text", self._meta_json())
        cb_block = view["blocks"][1]
        el = cb_block["element"]
        assert el["type"] == "checkboxes"
        assert el["action_id"] == ACTION_INCLUDE_DRAFT
        assert len(el["initial_options"]) == 1
        assert el["initial_options"][0]["value"] == "include"

    def test_draft_stored_in_private_metadata(self):
        view = _build_revise_modal_view("my draft", self._meta_json())
        pm = json.loads(view["private_metadata"])
        assert pm["draft"] == "my draft"
        assert pm["channel_id"] == "C1"

    def test_long_draft_truncated_in_private_metadata(self):
        long_draft = "x" * 5000
        view = _build_revise_modal_view(long_draft, self._meta_json())
        pm = json.loads(view["private_metadata"])
        assert len(view["private_metadata"]) <= 3000
        assert pm["draft"].endswith("...")
        assert pm["channel_id"] == "C1"


class TestBuildPrivateMetadata:
    def test_short_draft_preserved(self):
        meta_json = json.dumps({"a": "b"}, separators=(",", ":"))
        result = _build_private_metadata(meta_json, "hello")
        parsed = json.loads(result)
        assert parsed["draft"] == "hello"
        assert parsed["a"] == "b"

    def test_exceeding_limit_truncates_draft(self):
        meta_json = json.dumps({"k": "v"}, separators=(",", ":"))
        result = _build_private_metadata(meta_json, "z" * 5000)
        assert len(result) <= 3000
        parsed = json.loads(result)
        assert parsed["draft"].endswith("...")


class TestCheckboxIsSelected:
    def test_selected(self):
        values = {
            BLOCK_INCLUDE_DRAFT: {
                ACTION_INCLUDE_DRAFT: {
                    "selected_options": [{"value": "include"}],
                },
            },
        }
        assert _checkbox_is_selected(values) is True

    def test_not_selected(self):
        values = {
            BLOCK_INCLUDE_DRAFT: {
                ACTION_INCLUDE_DRAFT: {
                    "selected_options": [],
                },
            },
        }
        assert _checkbox_is_selected(values) is False

    def test_missing_block(self):
        assert _checkbox_is_selected({}) is False


class TestComposeReviseUserText:
    def test_with_draft_included(self):
        result = _compose_revise_user_text("be shorter", "old draft", True)
        assert "The original reply suggestion was:\nold draft" in result
        assert "The user requested a revision with this instruction:\nbe shorter" in result

    def test_without_draft(self):
        assert _compose_revise_user_text("be shorter", "old draft", False) == "be shorter"

    def test_include_but_empty_draft(self):
        assert _compose_revise_user_text("be shorter", "", True) == "be shorter"
