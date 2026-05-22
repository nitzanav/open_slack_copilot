import json
from pathlib import Path
from unittest.mock import patch

import pytest

from common.progressive_disclosure.progressive_disclosure import (
    select_skills, select_single_skill, _skill_entries_for_kind, _parse_selection,
)
from common.skill_runs import skill_runs
from common.skill_thumbs_up import skill_thumbs_up

FIXTURES = Path(__file__).parent.parent.parent / "tests" / "fixtures"

THREAD = [
    {"user": "U001", "text": "Can someone review PR #142?"},
    {"user": "U002", "text": "I'll take a look at the code changes"},
]


class TestSkillEntriesForKind:
    def test_loads_reply_skills(self, tmp_path):
        reply = tmp_path / "reply"
        reply.mkdir()
        for name in ("polite_reply", "code_review"):
            (reply / name).mkdir()
            (reply / name / "SKILL.md").write_text(f"{name} content")

        with patch("common.progressive_disclosure.progressive_disclosure.SKILLS_ROOT", tmp_path):
            entries = _skill_entries_for_kind("reply")
            refs = {ref for ref, _, _ in entries}
            assert refs == {"reply/polite_reply", "reply/code_review"}

    def test_ignores_other_kinds(self, tmp_path):
        watcher = tmp_path / "watcher"
        watcher.mkdir()
        (watcher / "check").mkdir()
        (watcher / "check" / "SKILL.md").write_text("watcher skill")

        with patch("common.progressive_disclosure.progressive_disclosure.SKILLS_ROOT", tmp_path):
            assert _skill_entries_for_kind("reply") == []

    def test_invalid_kind(self, tmp_path):
        with patch("common.progressive_disclosure.progressive_disclosure.SKILLS_ROOT", tmp_path):
            assert _skill_entries_for_kind("unknown") == []

    def test_missing_dir(self, tmp_path):
        with patch("common.progressive_disclosure.progressive_disclosure.SKILLS_ROOT", tmp_path):
            assert _skill_entries_for_kind("reply") == []


class TestParseSelection:
    def test_valid_json(self):
        assert _parse_selection('["polite_reply"]', ["polite_reply", "code_review"]) == ["polite_reply"]

    def test_multiple(self):
        result = _parse_selection('["polite_reply", "code_review"]', ["polite_reply", "code_review"])
        assert result == ["polite_reply", "code_review"]

    def test_filters_invalid_names(self):
        result = _parse_selection('["polite_reply", "nonexistent"]', ["polite_reply"])
        assert result == ["polite_reply"]

    def test_empty_array(self):
        assert _parse_selection("[]", ["polite_reply"]) == []

    def test_malformed_json(self):
        assert _parse_selection("not json", ["polite_reply"]) == []

    def test_json_with_surrounding_text(self):
        result = _parse_selection('Sure! ["polite_reply"]', ["polite_reply"])
        assert result == ["polite_reply"]


class TestSelectSkills:
    @patch("common.progressive_disclosure.progressive_disclosure.llm_client")
    def test_select_single_match(self, mock_llm, tmp_path):
        skill_dir = tmp_path / "reply"
        skill_dir.mkdir()
        (skill_dir / "polite_reply").mkdir()
        (skill_dir / "polite_reply" / "SKILL.md").write_text("Be polite.")

        mock_llm.generate.return_value = '["reply/polite_reply"]'

        with patch("common.progressive_disclosure.progressive_disclosure.SKILLS_ROOT", tmp_path):
            result = select_skills("reply", THREAD, "")
            assert len(result) == 1
            assert result[0][0] == "reply/polite_reply"
            assert result[0][1] == "Be polite."
            assert result[0][2] == {"main": "Be polite."}
            mock_llm.generate.assert_called_once()

    @patch("common.progressive_disclosure.progressive_disclosure.llm_client")
    def test_select_multiple_skills(self, mock_llm, tmp_path):
        skill_dir = tmp_path / "reply"
        skill_dir.mkdir()
        for name, content in [("sk_a", "Skill A"), ("sk_b", "Skill B")]:
            (skill_dir / name).mkdir()
            (skill_dir / name / "SKILL.md").write_text(content)

        mock_llm.generate.return_value = '["reply/sk_a", "reply/sk_b"]'

        with patch("common.progressive_disclosure.progressive_disclosure.SKILLS_ROOT", tmp_path):
            result = select_skills("reply", THREAD, "")
            texts = {t[1] for t in result}
            assert texts == {"Skill A", "Skill B"}

    @patch("common.progressive_disclosure.progressive_disclosure.llm_client")
    def test_does_not_include_watcher_skills_in_reply(self, mock_llm, tmp_path):
        reply = tmp_path / "reply"
        reply.mkdir()
        (reply / "r1").mkdir()
        (reply / "r1" / "SKILL.md").write_text("Reply skill")
        watcher = tmp_path / "watcher"
        watcher.mkdir()
        (watcher / "w1").mkdir()
        (watcher / "w1" / "SKILL.md").write_text("Watcher skill")

        mock_llm.generate.return_value = '["reply/r1"]'

        with patch("common.progressive_disclosure.progressive_disclosure.SKILLS_ROOT", tmp_path):
            result = select_skills("reply", THREAD, "")
            assert len(result) == 1
            assert result[0][0] == "reply/r1"
            assert result[0][1] == "Reply skill"
            prompt = mock_llm.generate.call_args[0][0]
            assert "watcher/w1" not in prompt

    @patch("common.progressive_disclosure.progressive_disclosure.llm_client")
    def test_no_match_returns_empty(self, mock_llm, tmp_path):
        skill_dir = tmp_path / "reply"
        skill_dir.mkdir()
        (skill_dir / "some_skill").mkdir()
        (skill_dir / "some_skill" / "SKILL.md").write_text("content")

        mock_llm.generate.return_value = "[]"

        with patch("common.progressive_disclosure.progressive_disclosure.SKILLS_ROOT", tmp_path):
            result = select_skills("reply", THREAD, "")
            assert result == []

    @patch("common.progressive_disclosure.progressive_disclosure.llm_client")
    def test_empty_skills_dir_no_llm_call(self, mock_llm, tmp_path):
        skill_dir = tmp_path / "reply"
        skill_dir.mkdir()

        with patch("common.progressive_disclosure.progressive_disclosure.SKILLS_ROOT", tmp_path):
            result = select_skills("reply", THREAD, "")
            assert result == []
            mock_llm.generate.assert_not_called()

    def test_missing_skills_dir_no_error(self, tmp_path):
        with patch("common.progressive_disclosure.progressive_disclosure.SKILLS_ROOT", tmp_path):
            result = select_skills("reply", THREAD, "")
            assert result == []


class TestSelectSingleSkill:
    @patch("common.progressive_disclosure.progressive_disclosure.llm_client")
    def test_returns_none_when_no_skills_installed(self, mock_llm, tmp_path):
        with patch("common.progressive_disclosure.progressive_disclosure.SKILLS_ROOT", tmp_path):
            assert select_single_skill("reply", THREAD, "") is None
            mock_llm.generate.assert_not_called()

    @patch("common.progressive_disclosure.progressive_disclosure.llm_client")
    def test_single_installed_skill_no_stage2_call(self, mock_llm, tmp_path):
        reply = tmp_path / "reply"
        reply.mkdir()
        (reply / "only_one").mkdir()
        (reply / "only_one" / "SKILL.md").write_text("Only one.")
        mock_llm.generate.return_value = '["reply/only_one"]'
        with patch("common.progressive_disclosure.progressive_disclosure.SKILLS_ROOT", tmp_path):
            picked = select_single_skill("reply", THREAD, "")
            assert picked is not None
            assert picked[0] == "reply/only_one"
            assert picked[1] == "Only one."
            assert picked[2] == {"main": "Only one."}
            assert mock_llm.generate.call_count == 1

    @patch("common.progressive_disclosure.progressive_disclosure.llm_client")
    def test_stage2_picks_valid_id(self, mock_llm, tmp_path):
        reply = tmp_path / "reply"
        reply.mkdir()
        for name, content in [("sk_a", "A"), ("sk_b", "B")]:
            (reply / name).mkdir()
            (reply / name / "SKILL.md").write_text(content)
        mock_llm.generate.side_effect = [
            '["reply/sk_a", "reply/sk_b"]',
            "reply/sk_b",
        ]
        with patch("common.progressive_disclosure.progressive_disclosure.SKILLS_ROOT", tmp_path):
            picked = select_single_skill("reply", THREAD, "")
            assert picked is not None
            assert picked[0] == "reply/sk_b"
            assert picked[1] == "B"

    @patch("common.progressive_disclosure.progressive_disclosure.llm_client")
    def test_stage2_parse_failure_falls_back_to_first(self, mock_llm, tmp_path):
        reply = tmp_path / "reply"
        reply.mkdir()
        for name, content in [("sk_a", "A"), ("sk_b", "B")]:
            (reply / name).mkdir()
            (reply / name / "SKILL.md").write_text(content)
        mock_llm.generate.side_effect = [
            '["reply/sk_a", "reply/sk_b"]',
            "garbage output not a skill id",
        ]
        with patch("common.progressive_disclosure.progressive_disclosure.SKILLS_ROOT", tmp_path):
            picked = select_single_skill("reply", THREAD, "")
            assert picked is not None
            assert picked[0] in {"reply/sk_a", "reply/sk_b"}

    @patch("common.progressive_disclosure.progressive_disclosure.llm_client")
    def test_no_stage1_match_uses_all_installed(self, mock_llm, tmp_path):
        reply = tmp_path / "reply"
        reply.mkdir()
        (reply / "only_one").mkdir()
        (reply / "only_one" / "SKILL.md").write_text("Only one.")
        mock_llm.generate.return_value = "[]"
        with patch("common.progressive_disclosure.progressive_disclosure.SKILLS_ROOT", tmp_path):
            picked = select_single_skill("reply", THREAD, "")
            assert picked is not None
            assert picked[0] == "reply/only_one"
            assert picked[1] == "Only one."


class TestExamplesInjection:
    def test_appends_examples_section_when_thumbs_up_present(self, tmp_path):
        skills_root = tmp_path / "skills"
        (skills_root / "reply" / "foo").mkdir(parents=True)
        (skills_root / "reply" / "foo" / "SKILL.md").write_text("Be foo.")
        from config.config import settings
        settings.set("data_layer.root", str(tmp_path / "data"))
        with patch("common.progressive_disclosure.progressive_disclosure.SKILLS_ROOT", skills_root), \
             patch("common.skill_thumbs_up.skill_thumbs_up.SKILLS_ROOT", skills_root):
            skill_runs.init_run(
                skill_id="reply/foo", channel_id="C1", thread_ts="T1",
                action_ts="A1", requester_user_id="U1",
                tool_name="send_dm_as_app", payload={"user_text": "draft"},
                text="Hello world.",
            )
            skill_thumbs_up.add_reference("reply/foo", "T1", "A1")
            entries = _skill_entries_for_kind("reply")
            assert len(entries) == 1
            _, text, _steps = entries[0]
            assert "Be foo." in text
            assert "## Examples (recent good runs)" in text
            assert "Hello world." in text

    def test_no_examples_section_when_no_thumbs_up(self, tmp_path):
        skills_root = tmp_path / "skills"
        (skills_root / "reply" / "foo").mkdir(parents=True)
        (skills_root / "reply" / "foo" / "SKILL.md").write_text("Be foo.")
        with patch("common.progressive_disclosure.progressive_disclosure.SKILLS_ROOT", skills_root), \
             patch("common.skill_thumbs_up.skill_thumbs_up.SKILLS_ROOT", skills_root):
            entries = _skill_entries_for_kind("reply")
            assert entries[0][1] == "Be foo."
            assert entries[0][2] == {"main": "Be foo."}
