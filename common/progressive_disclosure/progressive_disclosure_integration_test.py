from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

FIXTURES = Path(__file__).parent.parent.parent / "tests" / "fixtures"

THREAD = [
    {"user": "U001", "text": "Can someone review PR #142?"},
    {"user": "U002", "text": "I see issues with error handling in the new code"},
    {"user": "U003", "text": "The tests are also missing edge cases"},
]


class TestEndToEndSkillSelection:
    @patch("common.progressive_disclosure.progressive_disclosure.llm_client")
    def test_real_skills_dir_returns_content(self, mock_llm, tmp_path):
        skill_dir = tmp_path / "reply"
        skill_dir.mkdir()
        (skill_dir / "polite_reply").mkdir()
        (skill_dir / "polite_reply" / "SKILL.md").write_text("Be warm and professional.")

        mock_llm.generate.return_value = '["polite_reply"]'

        with patch("common.progressive_disclosure.progressive_disclosure.SKILLS_ROOT", tmp_path):
            from common.progressive_disclosure.progressive_disclosure import select_skills
            result = select_skills("reply", THREAD, "")
            assert result == ["Be warm and professional."]

    @patch("core.slack_bot.slack_rag")
    @patch("core.slack_bot.llm_client")
    @patch("common.progressive_disclosure.progressive_disclosure.llm_client")
    def test_slash_command_with_skills(self, mock_pd_llm, mock_bot_llm, mock_rag, tmp_path):
        skill_dir = tmp_path / "reply"
        skill_dir.mkdir()
        (skill_dir / "code_review").mkdir()
        (skill_dir / "code_review" / "SKILL.md").write_text("Review code carefully.")

        mock_pd_llm.generate.return_value = '["code_review"]'
        mock_bot_llm.generate.return_value = "Draft with code review skill"
        mock_rag.is_ready.return_value = True
        mock_rag.query_channel.return_value = []
        mock_rag.missing_channels.return_value = []
        mock_rag.query_cross_channel.return_value = []
        mock_config.return_value = {"rag": {"cross_channel": [], "checkpoint_duration": "30d"}}

        with patch("common.progressive_disclosure.progressive_disclosure.SKILLS_ROOT", tmp_path):
            from core.slack_bot import prepare_draft
            with patch("core.slack_bot.slack_api"):
                result = prepare_draft("C1", "T1", "U1", THREAD, "review this")

        assert result == "Draft with code review skill"
        draft_prompt = mock_bot_llm.generate.call_args[0][0]
        assert "Review code carefully." in draft_prompt
