import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from config.config import settings
from core.slack_bot import (
    compose_system_prompt, prepare_draft, _handle_copilot,
    _select_skills, _load_examples, _build_cross_channel_rags,
    _fetch_cross_channel_rag, DEFAULT_INSTRUCTION,
)

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

    def test_prompt_includes_skills(self):
        skills = ["Be polite.", "Be technical."]
        prompt = compose_system_prompt(THREAD_3, "", skills)
        assert "Skills" in prompt
        for s in skills:
            assert s in prompt

    def test_prompt_includes_rag_results(self):
        rag_results = [{"text": "deploy info"}]
        prompt = compose_system_prompt(THREAD_3, "", rag_results=rag_results)
        assert "Relevant Channel Context" in prompt
        assert "deploy info" in prompt

    def test_prompt_includes_cross_channel_rag(self):
        cross = [{"text": "cross-channel info", "channel": "eng"}]
        prompt = compose_system_prompt(THREAD_3, "", cross_rag_results=cross)
        assert "Cross-Channel Context" in prompt
        assert "cross-channel info" in prompt
        assert "Channel id: eng" in prompt

    def test_prompt_includes_examples(self):
        examples = [{"question": "How?", "answer": "Like this."}]
        prompt = compose_system_prompt(THREAD_3, "", examples=examples)
        assert "Example Replies" in prompt

    def test_prompt_ordering(self):
        prompt = compose_system_prompt(
            THREAD_3, "my instruction",
            skills=["skill1"], rag_results=[{"text": "rag1"}],
            cross_rag_results=[{"text": "cross1", "channel": "x"}],
            examples=[{"question": "q", "answer": "a"}]
        )
        assert prompt.index("Skills") < prompt.index("Relevant Channel Context")
        assert prompt.index("Relevant Channel Context") < prompt.index("Cross-Channel Context")
        assert prompt.index("Cross-Channel Context") < prompt.index("Example Replies")
        assert prompt.index("Example Replies") < prompt.index("## Thread")
        assert prompt.index("## Thread") < prompt.index("## Instruction")


class TestSelectSkills:
    @patch("core.slack_bot.progressive_disclosure")
    def test_returns_skills_when_matched(self, mock_pd):
        mock_pd.select_skills.return_value = ["Be polite."]
        assert _select_skills(THREAD_3, "") == ["Be polite."]

    @patch("core.slack_bot.progressive_disclosure")
    def test_falls_back_to_default(self, mock_pd):
        mock_pd.select_skills.return_value = []
        mock_pd.get_default_instruction.return_value = "Default"
        assert _select_skills(THREAD_3, "") == ["Default"]


class TestLoadExamples:
    def test_loads_example_threads(self):
        examples = _load_examples()
        assert len(examples) > 0


class TestCrossChannelRag:
    @patch("core.slack_bot.slack_rag")
    @patch("core.slack_bot.slack_api")
    def test_fetch_cross_channel_with_missing(self, mock_slack, mock_rag):
        original = list(settings.rag.cross_channel)
        settings.set("rag.cross_channel", ["eng", "prod"])
        try:
            mock_rag.missing_channels.return_value = ["prod"]
            mock_rag.query_cross_channel.return_value = [{"text": "cross result", "channel": "eng"}]

            result = _fetch_cross_channel_rag("support", "T1", "U1", "deploy question")

            mock_slack.send_ephemeral.assert_called_once()
            assert "prod" in mock_slack.send_ephemeral.call_args[0][3]
            mock_rag.build.assert_called_once_with("prod", 2592000.0)
            assert result == [{"text": "cross result", "channel": "eng"}]
        finally:
            settings.set("rag.cross_channel", original)

    @patch("core.slack_bot.slack_rag")
    def test_no_cross_channel_config(self, mock_rag):
        result = _fetch_cross_channel_rag("support", "T1", "U1", "context")
        assert result == []
        mock_rag.query_cross_channel.assert_not_called()

    @patch("core.slack_bot.slack_rag")
    def test_startup_builds_cross_channel(self, mock_rag):
        original = list(settings.rag.cross_channel)
        settings.set("rag.cross_channel", ["a", "b", "c"])
        try:
            _build_cross_channel_rags()
            mock_rag.build_all_missing.assert_called_once()
            assert mock_rag.build_all_missing.call_args[0][0] == ["a", "b", "c"]
        finally:
            settings.set("rag.cross_channel", original)


class TestPrepareDraft:
    @patch("core.slack_bot.slack_rag")
    @patch("core.slack_bot.progressive_disclosure")
    @patch("core.slack_bot.llm_client")
    @patch("core.slack_bot.slack_api")
    def test_full_draft_with_cross_channel(self, mock_slack, mock_llm, mock_pd, mock_rag):
        mock_pd.select_skills.return_value = []
        mock_pd.get_default_instruction.return_value = "default"
        mock_rag.is_ready.return_value = True
        mock_rag.query_channel.return_value = [{"text": "channel rag"}]
        mock_rag.missing_channels.return_value = []
        mock_rag.query_cross_channel.return_value = [{"text": "cross rag", "channel": "eng"}]
        mock_rag.format_rag_context_block.return_value = "unknown [-]: channel rag"
        mock_rag.format_cross_channel_rag_text.return_value = "unknown [-]: cross rag"
        mock_llm.generate.return_value = "Full draft"

        original = list(settings.rag.cross_channel)
        settings.set("rag.cross_channel", ["eng"])
        try:
            result = prepare_draft("support", "T1", "U1", THREAD_3, "")
            assert result == "Full draft"

            prompt = mock_llm.generate.call_args[0][0]
            assert "channel rag" in prompt
            assert "cross rag" in prompt
        finally:
            settings.set("rag.cross_channel", original)


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
        mock_rag.missing_channels.return_value = []
        mock_rag.query_cross_channel.return_value = []
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
        mock_rag.missing_channels.return_value = []
        mock_rag.query_cross_channel.return_value = []
        mock_llm.generate.side_effect = Exception("LLM down")

        _handle_copilot("C123", "T123", "U001", "", THREAD_3)
        assert "Failed to generate draft" in mock_slack.send_ephemeral.call_args[0][3]
