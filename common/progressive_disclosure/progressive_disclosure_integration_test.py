from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from common.conversations.conversations import Conversation
from common.llm.llm_client.llm_client import AgentToolLoopResult

FIXTURES = Path(__file__).parent.parent.parent / "tests" / "fixtures"

THREAD = [
    {"user": "U001", "text": "Can someone review PR #142?"},
    {"user": "U002", "text": "I see issues with error handling in the new code"},
    {"user": "U003", "text": "The tests are also missing edge cases"},
]


@pytest.fixture(autouse=True)
def _isolated_data_layer(tmp_path):
    from config.config import settings

    settings.set("data_layer.root", str(tmp_path))
    yield


class TestEndToEndSkillSelection:
    @patch("common.progressive_disclosure.progressive_disclosure.llm_client")
    def test_real_skills_dir_returns_content(self, mock_llm, tmp_path):
        skill_dir = tmp_path / "reply"
        skill_dir.mkdir()
        (skill_dir / "polite_reply").mkdir()
        (skill_dir / "polite_reply" / "SKILL.md").write_text("Be warm and professional.")

        mock_llm.generate.return_value = '["reply/polite_reply"]'

        with patch("common.progressive_disclosure.progressive_disclosure.SKILLS_ROOT", tmp_path):
            from common.progressive_disclosure.progressive_disclosure import select_skills
            result = select_skills("reply", THREAD, "")
            assert len(result) == 1
            assert result[0][0] == "reply/polite_reply"
            assert result[0][1] == "Be warm and professional."
            assert result[0][2] == {"main": "Be warm and professional."}

    @patch("common.slack.copilot_pipeline.run_conversation_driver")
    @patch("common.slack.copilot_pipeline.fetch_thread_messages")
    @patch("common.slack.copilot_pipeline.slack_rag")
    @patch("common.progressive_disclosure.progressive_disclosure.llm_client")
    def test_slash_command_with_skills(self, mock_pd_llm, mock_rag, mock_fetch, mock_driver, tmp_path):
        skill_dir = tmp_path / "reply"
        skill_dir.mkdir()
        (skill_dir / "code_review").mkdir()
        (skill_dir / "code_review" / "SKILL.md").write_text("Review code carefully.")

        mock_pd_llm.generate.return_value = '["reply/code_review"]'
        mock_driver.return_value = (AgentToolLoopResult("Draft with code review skill", []), Conversation())
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
        assert mock_driver.called
