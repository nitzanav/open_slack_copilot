import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from config.config import settings
from common.llm.llm_client.llm_client import AgentToolLoopResult
from common.slack.copilot_pipeline import ThreadFetchError
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

    def test_includes_agent_log_section(self):
        section = "## Agent log\n\n[2026-01-01 12:00] slash command - suggested draft: prior\n"
        prompt = compose_system_prompt(THREAD_3, "go", agent_log_section=section)
        assert "## Agent log" in prompt
        assert "slash command" in prompt
        assert prompt.index("## Agent log") < prompt.index("## Thread")

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
    @patch("common.slack.copilot_pipeline.progressive_disclosure")
    def test_returns_skills_when_matched(self, mock_pd):
        mock_pd.select_skills.return_value = ["Be polite."]
        assert _select_skills(THREAD_3, "") == ["Be polite."]

    @patch("common.slack.copilot_pipeline.progressive_disclosure")
    def test_falls_back_to_default(self, mock_pd):
        mock_pd.select_skills.return_value = []
        mock_pd.get_default_instruction.return_value = "Default"
        assert _select_skills(THREAD_3, "") == ["Default"]


class TestLoadExamples:
    def test_loads_example_threads(self):
        examples = _load_examples()
        assert len(examples) > 0


class TestCrossChannelRag:
    @patch("common.slack.copilot_pipeline.slack_rag")
    @patch("common.slack.copilot_pipeline.slack_api")
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

    @patch("common.slack.copilot_pipeline.slack_rag")
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
    @patch("common.slack.copilot_pipeline.fetch_thread_messages")
    @patch("common.slack.copilot_pipeline.slack_rag")
    @patch("common.slack.copilot_pipeline.progressive_disclosure")
    @patch("common.slack.copilot_pipeline.llm_client")
    @patch("common.slack.copilot_pipeline.slack_api")
    def test_full_draft_with_cross_channel(
        self, mock_slack, mock_llm, mock_pd, mock_rag, mock_fetch,
    ):
        mock_pd.select_skills.return_value = []
        mock_pd.get_default_instruction.return_value = "default"
        mock_rag.is_ready.return_value = True
        mock_rag.query_channel.return_value = [{"text": "channel rag"}]
        mock_rag.missing_channels.return_value = []
        mock_rag.query_cross_channel.return_value = [{"text": "cross rag", "channel": "eng"}]
        mock_rag.format_rag_context_block.return_value = "unknown [-]: channel rag"
        mock_rag.format_cross_channel_rag_text.return_value = "unknown [-]: cross rag"
        mock_llm.agent_tool_loop.return_value = AgentToolLoopResult("Full draft", [])
        mock_fetch.return_value = THREAD_3

        original = list(settings.rag.cross_channel)
        settings.set("rag.cross_channel", ["eng"])
        try:
            result = prepare_draft("support", "T1", "U1", "")
            assert result == "Full draft"

            prompt = mock_llm.agent_tool_loop.call_args[0][0]
            assert "channel rag" in prompt
            assert "cross rag" in prompt
        finally:
            settings.set("rag.cross_channel", original)


class TestPrepareDraftPreloadedMessages:
    @patch("common.slack.copilot_pipeline.fetch_thread_messages")
    @patch("common.slack.copilot_pipeline.slack_rag")
    @patch("common.slack.copilot_pipeline.progressive_disclosure")
    @patch("common.slack.copilot_pipeline.llm_client")
    @patch("common.slack.copilot_pipeline.slack_api")
    def test_skips_fetch_when_thread_messages_provided(
        self, mock_slack, mock_llm, mock_pd, mock_rag, mock_fetch,
    ):
        mock_pd.select_skills.return_value = []
        mock_pd.get_default_instruction.return_value = "default"
        mock_rag.is_ready.return_value = True
        mock_rag.query_channel.return_value = []
        mock_rag.missing_channels.return_value = []
        mock_rag.query_cross_channel.return_value = []
        mock_llm.agent_tool_loop.return_value = AgentToolLoopResult("ok", [])

        result = prepare_draft("C", "T1", "U1", "", thread_messages=THREAD_3)
        assert result == "ok"
        mock_fetch.assert_not_called()


class TestHandleCopilot:
    @patch("common.slack.slack_bot.draft_delivery.fetch_thread_messages")
    @patch("common.slack.copilot_pipeline.slack_rag")
    @patch("common.slack.copilot_pipeline.progressive_disclosure")
    @patch("common.slack.slack_bot.draft_revise_actions.send_draft_ephemeral_with_revise")
    @patch("common.slack.slack_bot.draft_delivery.slack_api")
    @patch("common.slack.copilot_pipeline.llm_client")
    def test_draft_sent_as_ephemeral(self, mock_llm, mock_slack, mock_send_rev, mock_pd, mock_rag, mock_fetch):
        mock_pd.select_skills.return_value = []
        mock_pd.get_default_instruction.return_value = "default"
        mock_rag.is_ready.return_value = True
        mock_rag.query_channel.return_value = []
        mock_rag.missing_channels.return_value = []
        mock_rag.query_cross_channel.return_value = []
        mock_llm.agent_tool_loop.return_value = AgentToolLoopResult("Here is my draft", [])
        mock_fetch.return_value = THREAD_3

        _handle_copilot("C123", "T123", "U001", "help")
        mock_send_rev.assert_called_once_with(
            "C123",
            "T123",
            "U001",
            "U001",
            "Here is my draft",
            context_kind="thread",
        )

    @patch("common.slack.slack_bot.draft_delivery.fetch_thread_messages")
    @patch("common.slack.copilot_pipeline.slack_rag")
    @patch("common.slack.copilot_pipeline.progressive_disclosure")
    @patch("common.slack.slack_bot.draft_delivery.slack_api")
    @patch("common.slack.copilot_pipeline.llm_client")
    def test_llm_error_sends_error_ephemeral(self, mock_llm, mock_slack, mock_pd, mock_rag, mock_fetch):
        mock_pd.select_skills.return_value = []
        mock_pd.get_default_instruction.return_value = "default"
        mock_rag.is_ready.return_value = True
        mock_rag.query_channel.return_value = []
        mock_rag.missing_channels.return_value = []
        mock_rag.query_cross_channel.return_value = []
        mock_llm.agent_tool_loop.side_effect = Exception("LLM down")
        mock_fetch.return_value = THREAD_3

        _handle_copilot("C123", "T123", "U001", "")
        assert "Failed to process" in mock_slack.send_ephemeral.call_args[0][3]

    @patch("common.slack.slack_bot.draft_delivery.fetch_thread_messages")
    @patch("common.slack.copilot_pipeline.slack_rag")
    @patch("common.slack.copilot_pipeline.progressive_disclosure")
    @patch("common.slack.slack_bot.draft_delivery.slack_api")
    @patch("common.slack.copilot_pipeline.llm_client")
    def test_thread_fetch_error_sends_invite_ephemeral(
        self, mock_llm, mock_slack, mock_pd, mock_rag, mock_fetch,
    ):
        mock_fetch.side_effect = ThreadFetchError("not in channel")
        _handle_copilot("C123", "T123", "U001", "hi")
        msg = mock_slack.send_ephemeral.call_args[0][3]
        assert "invite" in msg.lower()
        mock_llm.agent_tool_loop.assert_not_called()

    @patch("common.slack.slack_bot.draft_delivery.fetch_thread_messages")
    @patch("common.slack.copilot_pipeline.slack_rag")
    @patch("common.slack.copilot_pipeline.progressive_disclosure")
    @patch("common.slack.slack_bot.draft_revise_actions.send_draft_ephemeral_with_revise")
    @patch("common.slack.copilot_pipeline.llm_client")
    def test_empty_draft_sends_no_action_taken(
        self, mock_llm, mock_send_rev, mock_pd, mock_rag, mock_fetch,
    ):
        mock_pd.select_skills.return_value = []
        mock_pd.get_default_instruction.return_value = "default"
        mock_rag.is_ready.return_value = True
        mock_rag.query_channel.return_value = []
        mock_rag.missing_channels.return_value = []
        mock_rag.query_cross_channel.return_value = []
        mock_llm.agent_tool_loop.return_value = AgentToolLoopResult("", [])
        mock_fetch.return_value = THREAD_3

        _handle_copilot("C123", "T123", "U001", "help")
        mock_send_rev.assert_called_once()
        assert mock_send_rev.call_args[0][4] == "No action taken."
