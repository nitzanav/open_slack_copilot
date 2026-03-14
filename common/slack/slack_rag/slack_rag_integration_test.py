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

ENGINEERING_HISTORY = [
    {"user": "U4", "text": "New architecture proposal for microservices", "ts": "1800000001.000"},
    {"user": "U5", "text": "We should use event-driven design", "ts": "1800000002.000"},
    {"user": "U4", "text": "Performance benchmarks look good", "ts": "1800000003.000"},
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


class TestCrossChannelIntegration:
    @patch("common.slack.slack_rag.slack_rag.slack_api")
    @patch("common.slack.slack_rag.slack_rag.llm_client")
    def test_startup_to_query(self, mock_llm, mock_slack):
        def history_side_effect(channel_id, oldest=0, limit=1000):
            if channel_id == "eng":
                return ENGINEERING_HISTORY
            return CHANNEL_HISTORY
        mock_slack.read_channel_history.side_effect = history_side_effect
        mock_llm.generate.return_value = "summary"

        threads = slack_rag.build_all_missing(["eng", "support"])
        for t in threads:
            t.join(timeout=5)

        results = slack_rag.query_cross_channel(["eng", "support"], "architecture")
        assert len(results) > 0

    @patch("common.slack.slack_rag.slack_rag.slack_api")
    @patch("common.slack.slack_rag.slack_rag.llm_client")
    def test_full_draft_with_channel_and_cross_channel(self, mock_llm, mock_slack):
        def history_side_effect(channel_id, oldest=0, limit=1000):
            if channel_id == "eng":
                return ENGINEERING_HISTORY
            return CHANNEL_HISTORY
        mock_slack.read_channel_history.side_effect = history_side_effect
        mock_llm.generate.return_value = "summary"

        slack_rag.build("support")
        slack_rag.build("eng")

        channel_results = slack_rag.query_channel("support", "deployment")
        cross_results = slack_rag.query_cross_channel(["eng"], "architecture", exclude_channel="support")

        assert len(channel_results) > 0
        assert len(cross_results) > 0
