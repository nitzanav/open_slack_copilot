import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from core.slack_bot import compose_system_prompt, prepare_draft, _handle_copilot, _select_skills, _load_examples, DEFAULT_INSTRUCTION

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"


def _load_fixture(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text())


THREAD_3 = _load_fixture("fixture_thread_3_messages.json")
THREAD_1 = _load_fixture("fixture_thread_singleton.json")
THREAD_50 = _load_fixture("fixture_thread_50_messages.json")


class TestComposeSystemPrompt:
    def test_with_instruction(self):
        prompt = compose_system_prompt(THREAD_3, "suggest a polite reply")
        assert "suggest a polite reply" in prompt
        for msg in THREAD_3:
            assert msg["text"] in prompt

    def test_empty_text_uses_default(self):
        prompt = compose_system_prompt(THREAD_3, "")
        assert DEFAULT_INSTRUCTION in prompt

    def test_singleton_thread(self):
        prompt = compose_system_prompt(THREAD_1, "")
        assert THREAD_1[0]["text"] in prompt

    def test_large_thread_all_included(self):
        prompt = compose_system_prompt(THREAD_50, "summarize and reply")
        for msg in THREAD_50:
            assert msg["text"] in prompt

    def test_prompt_includes_skills(self):
        skills = ["Be polite and professional.", "Focus on technical accuracy."]
        prompt = compose_system_prompt(THREAD_3, "", skills)
        assert "Skills" in prompt
        for s in skills:
            assert s in prompt

    def test_user_text_positioned_after_skills(self):
        skills = ["Skill content here"]
        prompt = compose_system_prompt(THREAD_3, "be casual", skills)
        assert prompt.index("be casual") > prompt.index("Skill content here")

    def test_prompt_includes_rag_results(self):
        rag_results = [{"text": "Previous deployment failed due to config"}, {"text": "Use rollback command"}]
        prompt = compose_system_prompt(THREAD_3, "", rag_results=rag_results)
        assert "Relevant Channel Context" in prompt
        assert "Previous deployment failed" in prompt

    def test_prompt_includes_examples(self):
        examples = [{"question": "How to deploy?", "answer": "Use CI/CD pipeline"}]
        prompt = compose_system_prompt(THREAD_3, "", examples=examples)
        assert "Example Replies" in prompt
        assert "How to deploy?" in prompt

    def test_prompt_ordering(self):
        prompt = compose_system_prompt(
            THREAD_3, "my instruction",
            skills=["skill1"], rag_results=[{"text": "rag1"}],
            examples=[{"question": "q", "answer": "a"}]
        )
        assert prompt.index("Skills") < prompt.index("Relevant Channel Context")
        assert prompt.index("Relevant Channel Context") < prompt.index("Example Replies")
        assert prompt.index("Example Replies") < prompt.index("Thread")
        assert prompt.index("Thread") < prompt.index("Instruction")


class TestSelectSkills:
    @patch("core.slack_bot.progressive_disclosure")
    def test_returns_skills_when_matched(self, mock_pd):
        mock_pd.select_skills.return_value = ["Be polite."]
        assert _select_skills(THREAD_3, "") == ["Be polite."]

    @patch("core.slack_bot.progressive_disclosure")
    def test_falls_back_to_default_when_no_match(self, mock_pd):
        mock_pd.select_skills.return_value = []
        mock_pd.get_default_instruction.return_value = "Default instruction"
        assert _select_skills(THREAD_3, "") == ["Default instruction"]


class TestLoadExamples:
    def test_loads_example_threads(self):
        examples = _load_examples()
        assert len(examples) > 0
        assert "question" in examples[0]
        assert "answer" in examples[0]


class TestPrepareDraft:
    @patch("core.slack_bot.slack_rag")
    @patch("core.slack_bot.progressive_disclosure")
    @patch("core.slack_bot.llm_client")
    def test_calls_llm_and_returns_draft(self, mock_llm, mock_pd, mock_rag):
        mock_pd.select_skills.return_value = []
        mock_pd.get_default_instruction.return_value = "default"
        mock_rag.is_ready.return_value = False
        mock_rag.query_channel.return_value = []
        mock_llm.generate.return_value = "Here is my draft"

        with patch("core.slack_bot.slack_api"):
            result = prepare_draft("C1", "T1", "U1", THREAD_3, "help me reply")
        assert result == "Here is my draft"


class TestHandleCopilot:
    @patch("core.slack_bot.slack_rag")
    @patch("core.slack_bot.progressive_disclosure")
    @patch("core.slack_bot.slack_api")
    @patch("core.slack_bot.llm_client")
    def test_draft_sent_as_ephemeral(self, mock_llm, mock_slack, mock_pd, mock_rag):
        mock_pd.select_skills.return_value = []
        mock_pd.get_default_instruction.return_value = "default"
        mock_rag.is_ready.return_value = True
        mock_rag.query_channel.return_value = []
        mock_llm.generate.return_value = "Here is my draft"

        _handle_copilot("C123", "T123", "U001", "help", THREAD_3)
        mock_slack.send_ephemeral.assert_called_with("C123", "T123", "U001", "Here is my draft")

    @patch("core.slack_bot.slack_rag")
    @patch("core.slack_bot.progressive_disclosure")
    @patch("core.slack_bot.slack_api")
    @patch("core.slack_bot.llm_client")
    def test_llm_error_sends_error_ephemeral(self, mock_llm, mock_slack, mock_pd, mock_rag):
        mock_pd.select_skills.return_value = []
        mock_pd.get_default_instruction.return_value = "default"
        mock_rag.is_ready.return_value = True
        mock_rag.query_channel.return_value = []
        mock_llm.generate.side_effect = Exception("LLM down")

        _handle_copilot("C123", "T123", "U001", "", THREAD_3)
        assert "Failed to generate draft" in mock_slack.send_ephemeral.call_args[0][3]
