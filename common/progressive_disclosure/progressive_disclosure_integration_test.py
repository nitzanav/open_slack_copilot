from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from common.llm.llm_client.llm_client import AgentToolLoopResult

FIXTURES = Path(__file__).parent.parent.parent / "tests" / "fixtures"

THREAD = [
    {"user": "U001", "text": "Can someone review PR #142?"},
    {"user": "U002", "text": "I see issues with error handling in the new code"},
    {"user": "U003", "text": "The tests are also missing edge cases"},
]


class TestEndToEndSkillSelection:
    @patch("common.progressive_disclosure.progressive_disclosure.llm_client")
    def test_real_skills_dir_returns_content(self, mock_llm, tmp_path):
        (tmp_path / "polite_reply").mkdir()
        (tmp_path / "polite_reply" / "SKILL.md").write_text("Be warm and professional.")

        mock_llm.generate.return_value = '["polite_reply"]'

        with patch("common.progressive_disclosure.progressive_disclosure.SKILLS_ROOT", tmp_path):
            from common.progressive_disclosure.progressive_disclosure import select_skills
            result = select_skills(THREAD, "")
            assert result == ["Be warm and professional."]

    @patch("common.slack.copilot_pipeline.fetch_thread_messages")
    @patch("common.slack.copilot_pipeline.slack_rag")
    @patch("common.slack.copilot_pipeline.llm_client")
    @patch("common.progressive_disclosure.progressive_disclosure.llm_client")
    def test_slash_command_with_skills(self, mock_pd_llm, mock_bot_llm, mock_rag, mock_fetch, tmp_path):
        (tmp_path / "code_review").mkdir()
        (tmp_path / "code_review" / "SKILL.md").write_text("Review code carefully.")

        mock_pd_llm.generate.return_value = '["code_review"]'
        mock_bot_llm.agent_tool_loop.return_value = AgentToolLoopResult("Draft with code review skill", [])
        mock_rag.is_ready.return_value = True
        mock_rag.query_channel.return_value = []
        mock_rag.missing_channels.return_value = []
        mock_rag.query_cross_channel.return_value = []
        mock_fetch.return_value = THREAD

        with patch("common.progressive_disclosure.progressive_disclosure.SKILLS_ROOT", tmp_path):
            from common.slack.copilot_pipeline import run_react_loop
            with patch("common.slack.copilot_pipeline.slack_api"):
                result = run_react_loop("C1", "T1", "U1", "review this")

        assert result.text == "Draft with code review skill"
        draft_prompt = mock_bot_llm.agent_tool_loop.call_args[0][0]
        assert "Review code carefully." in draft_prompt
