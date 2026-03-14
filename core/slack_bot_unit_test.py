import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from core.slack_bot import compose_system_prompt, prepare_draft, _handle_copilot, DEFAULT_INSTRUCTION

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

    def test_with_draft_text(self):
        prompt = compose_system_prompt(THREAD_3, "I agree and want to be informed")
        assert "I agree and want to be informed" in prompt
        assert "Thread" in prompt

    def test_empty_text_uses_default(self):
        prompt = compose_system_prompt(THREAD_3, "")
        assert DEFAULT_INSTRUCTION in prompt

    def test_singleton_thread(self):
        prompt = compose_system_prompt(THREAD_1, "")
        assert THREAD_1[0]["text"] in prompt
        assert DEFAULT_INSTRUCTION in prompt

    def test_large_thread_all_included(self):
        prompt = compose_system_prompt(THREAD_50, "summarize and reply")
        for msg in THREAD_50:
            assert msg["text"] in prompt

    def test_thread_format_includes_user_ids(self):
        prompt = compose_system_prompt(THREAD_3, "")
        for msg in THREAD_3:
            assert f"<@{msg['user']}>" in prompt


class TestPrepareDraft:
    @patch("core.slack_bot.llm_client")
    def test_calls_llm_and_returns_draft(self, mock_llm):
        mock_llm.generate.return_value = "Here is my draft"
        result = prepare_draft(THREAD_3, "help me reply")
        assert result == "Here is my draft"
        mock_llm.generate.assert_called_once()

    @patch("core.slack_bot.llm_client")
    def test_llm_receives_system_prompt(self, mock_llm):
        mock_llm.generate.return_value = "draft"
        prepare_draft(THREAD_3, "be polite")
        prompt = mock_llm.generate.call_args[0][0]
        assert "be polite" in prompt
        assert "Thread" in prompt


class TestHandleCopilot:
    @patch("core.slack_bot.slack_api")
    @patch("core.slack_bot.llm_client")
    def test_draft_sent_as_ephemeral(self, mock_llm, mock_slack):
        mock_llm.generate.return_value = "Here is my draft"
        _handle_copilot("C123", "T123", "U001", "help", THREAD_3)
        mock_slack.send_ephemeral.assert_called_once_with("C123", "T123", "U001", "Here is my draft")

    @patch("core.slack_bot.slack_api")
    @patch("core.slack_bot.llm_client")
    def test_ephemeral_targets_correct_user(self, mock_llm, mock_slack):
        mock_llm.generate.return_value = "draft"
        _handle_copilot("C999", "T999", "U777", "", THREAD_1)
        call_args = mock_slack.send_ephemeral.call_args
        assert call_args[0] == ("C999", "T999", "U777", "draft")

    @patch("core.slack_bot.slack_api")
    @patch("core.slack_bot.llm_client")
    def test_llm_error_sends_error_ephemeral(self, mock_llm, mock_slack):
        mock_llm.generate.side_effect = Exception("LLM down")
        _handle_copilot("C123", "T123", "U001", "", THREAD_3)
        mock_slack.send_ephemeral.assert_called_once()
        assert "Failed to generate draft" in mock_slack.send_ephemeral.call_args[0][3]

    @patch("core.slack_bot.slack_api")
    @patch("core.slack_bot.llm_client")
    def test_singleton_thread_draft_generated(self, mock_llm, mock_slack):
        mock_llm.generate.return_value = "singleton draft"
        _handle_copilot("C123", "T123", "U001", "", THREAD_1)
        mock_slack.send_ephemeral.assert_called_once_with("C123", "T123", "U001", "singleton draft")
