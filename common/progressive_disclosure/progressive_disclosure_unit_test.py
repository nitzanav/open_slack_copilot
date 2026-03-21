import json
from pathlib import Path
from unittest.mock import patch

import pytest

from common.progressive_disclosure.progressive_disclosure import (
    select_skills, get_default_instruction, _load_skill_titles, _parse_selection,
    _BUNDLED_DEFAULT_INSTRUCTION,
)

FIXTURES = Path(__file__).parent.parent.parent / "tests" / "fixtures"
SKILLS_DIR = FIXTURES / "fixture_skills_dir"

THREAD = [
    {"user": "U001", "text": "Can someone review PR #142?"},
    {"user": "U002", "text": "I'll take a look at the code changes"},
]


class TestLoadSkillTitles:
    def test_loads_three_skills(self):
        titles = _load_skill_titles(SKILLS_DIR)
        assert len(titles) == 3
        assert set(titles) == {"polite_reply", "technical_review", "code_review"}

    def test_empty_dir(self, tmp_path):
        assert _load_skill_titles(tmp_path) == []

    def test_missing_dir(self):
        assert _load_skill_titles(Path("/nonexistent/path")) == []


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
    def test_select_single_skill(self, mock_llm, tmp_path):
        skill_dir = tmp_path / "reply"
        skill_dir.mkdir()
        (skill_dir / "polite_reply").mkdir()
        (skill_dir / "polite_reply" / "SKILL.md").write_text("Be polite.")

        mock_llm.generate.return_value = '["reply/polite_reply"]'

        with patch("common.progressive_disclosure.progressive_disclosure.SKILLS_ROOT", tmp_path):
            result = select_skills("reply", THREAD, "")
            assert result == ["Be polite."]
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
            assert set(result) == {"Skill A", "Skill B"}

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


class TestGetDefaultInstruction:
    def test_returns_bundled_when_no_user_override(self, tmp_path):
        missing = tmp_path / "no_such_file.md"
        with patch("common.progressive_disclosure.progressive_disclosure.USER_DEFAULT_INSTRUCTION_PATH", missing):
            result = get_default_instruction()
            assert result == _BUNDLED_DEFAULT_INSTRUCTION
            assert len(result) > 0

    def test_user_override_takes_precedence(self, tmp_path):
        override = tmp_path / "default.md"
        override.write_text("  Custom user instruction  \n")
        with patch("common.progressive_disclosure.progressive_disclosure.USER_DEFAULT_INSTRUCTION_PATH", override):
            assert get_default_instruction() == "Custom user instruction"

    def test_user_override_ignores_directory(self, tmp_path):
        dir_path = tmp_path / "default.md"
        dir_path.mkdir()
        with patch("common.progressive_disclosure.progressive_disclosure.USER_DEFAULT_INSTRUCTION_PATH", dir_path):
            assert get_default_instruction() == _BUNDLED_DEFAULT_INSTRUCTION
