from unittest.mock import patch, MagicMock

import pytest
from qdrant_client import QdrantClient

from common.rag import rag
from common.slack.slack_rag import slack_rag


@pytest.fixture(autouse=True)
def fresh_qdrant():
    rag.set_client(QdrantClient(location=":memory:"))
    yield


CHANNEL_HISTORY = [
    {"user": "U1", "text": "The deployment pipeline is broken again", "ts": "1700000001.000"},
    {"user": "U2", "text": "I fixed the staging config yesterday", "ts": "1700000002.000"},
    {"user": "U3", "text": "We need better monitoring for production", "ts": "1700000003.000"},
    {"user": "U1", "text": "Can someone review the latest PR?", "ts": "1700000004.000"},
    {"user": "U2", "text": "The database migration failed on staging", "ts": "1700000005.000"},
]


class TestBuildThenQuery:
    @patch("common.slack.slack_rag.slack_rag.slack_api")
    @patch("common.slack.slack_rag.slack_rag.llm_client")
    def test_build_and_query_returns_results(self, mock_llm, mock_slack):
        mock_slack.read_channel_history.return_value = CHANNEL_HISTORY
        mock_llm.generate.side_effect = lambda p: p.split("\n\n")[-1][:80]

        slack_rag.build("C_int")
        results = slack_rag.query_channel("C_int", "deployment issue")

        assert len(results) > 0
        assert all("text" in r for r in results)

    @patch("common.slack.slack_rag.slack_rag.slack_api")
    @patch("common.slack.slack_rag.slack_rag.llm_client")
    def test_refresh_replaces_old_data(self, mock_llm, mock_slack):
        mock_slack.read_channel_history.return_value = CHANNEL_HISTORY[:2]
        mock_llm.generate.return_value = "old summary"
        slack_rag.build("C_refresh")

        old_results = slack_rag.query_channel("C_refresh", "anything", top_k=100)

        mock_slack.read_channel_history.return_value = CHANNEL_HISTORY
        mock_llm.generate.return_value = "new summary"
        slack_rag.build("C_refresh")

        new_results = slack_rag.query_channel("C_refresh", "anything", top_k=100)
        assert len(new_results) > len(old_results)


class TestSlashCommandWithRag:
    @patch("core.slack_bot.progressive_disclosure")
    @patch("core.slack_bot.llm_client")
    @patch("common.slack.slack_rag.slack_rag.slack_api")
    @patch("common.slack.slack_rag.slack_rag.llm_client")
    def test_draft_includes_rag_in_prompt(self, mock_rag_llm, mock_rag_slack, mock_bot_llm, mock_pd):
        mock_rag_slack.read_channel_history.return_value = CHANNEL_HISTORY
        mock_rag_llm.generate.side_effect = lambda p: p.split("\n\n")[-1][:80]

        slack_rag.build("C_draft")

        mock_pd.select_skills.return_value = []
        mock_pd.get_default_instruction.return_value = "default"
        mock_bot_llm.generate.return_value = "Draft with RAG"

        with patch("core.slack_bot.slack_rag") as mock_sr:
            mock_sr.is_ready.return_value = True
            mock_sr.query_channel.return_value = [{"text": "deployment pipeline summary"}]

            from core.slack_bot import prepare_draft
            with patch("core.slack_bot.slack_api"):
                result = prepare_draft("C_draft", "T1", "U1",
                                       [{"user": "U1", "text": "help with deploy"}], "")

        assert result == "Draft with RAG"
        prompt = mock_bot_llm.generate.call_args[0][0]
        assert "deployment pipeline summary" in prompt
