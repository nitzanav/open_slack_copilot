import time
from unittest.mock import patch, MagicMock

import pytest
from qdrant_client import QdrantClient

from common.rag import rag
from common.slack.slack_rag import slack_rag


@pytest.fixture(autouse=True)
def fresh_qdrant():
    rag.set_client(QdrantClient(location=":memory:"))
    yield


CHANNEL_MESSAGES = [
    {"user": "U1", "text": f"Message about deployment issue {i}", "ts": f"170000{i:04d}.000"}
    for i in range(15)
]


class TestBuild:
    @patch("common.slack.slack_rag.slack_rag.slack_api")
    @patch("common.slack.slack_rag.slack_rag.llm_client")
    def test_build_fetches_from_checkpoint(self, mock_llm, mock_slack):
        mock_slack.read_channel_history.return_value = CHANNEL_MESSAGES[:3]
        mock_llm.generate.side_effect = lambda p: f"Summary of: {p[-30:]}"

        slack_rag.build("C1", checkpoint_seconds=30 * 86400)

        call_args = mock_slack.read_channel_history.call_args
        assert call_args[0][0] == "C1"
        assert call_args[1]["oldest"] > 0

    @patch("common.slack.slack_rag.slack_rag.slack_api")
    @patch("common.slack.slack_rag.slack_rag.llm_client")
    def test_build_summarizes_each_message(self, mock_llm, mock_slack):
        mock_slack.read_channel_history.return_value = CHANNEL_MESSAGES[:5]
        mock_llm.generate.return_value = "A summary"

        slack_rag.build("C2")
        assert mock_llm.generate.call_count == 5

    @patch("common.slack.slack_rag.slack_rag.slack_api")
    @patch("common.slack.slack_rag.slack_rag.llm_client")
    def test_build_inserts_into_qdrant(self, mock_llm, mock_slack):
        mock_slack.read_channel_history.return_value = CHANNEL_MESSAGES[:3]
        mock_llm.generate.return_value = "Deployment issue summary"

        slack_rag.build("C3")

        results = slack_rag.query_channel("C3", "deployment")
        assert len(results) == 3

    @patch("common.slack.slack_rag.slack_rag.slack_api")
    @patch("common.slack.slack_rag.slack_rag.llm_client")
    def test_build_failure_releases_lock(self, mock_llm, mock_slack):
        mock_slack.read_channel_history.side_effect = Exception("API error")

        with pytest.raises(Exception):
            slack_rag.build("C_fail")

        lock = rag.acquire_lock("C_fail")
        assert lock.acquire(timeout=0.1)
        lock.release()


class TestQuery:
    @patch("common.slack.slack_rag.slack_rag.slack_api")
    @patch("common.slack.slack_rag.slack_rag.llm_client")
    def test_query_returns_top_10(self, mock_llm, mock_slack):
        mock_slack.read_channel_history.return_value = CHANNEL_MESSAGES
        mock_llm.generate.side_effect = lambda p: f"Summary {CHANNEL_MESSAGES.index(next((m for m in CHANNEL_MESSAGES if m['text'][-10:] in p), CHANNEL_MESSAGES[0]))}" if "Summarize" in p else "summary"

        slack_rag.build("C_many")
        results = slack_rag.query_channel("C_many", "deployment issue")
        assert len(results) == 10

    def test_query_empty_channel(self):
        results = slack_rag.query_channel("nonexistent", "anything")
        assert results == []


class TestStatus:
    @patch("common.slack.slack_rag.slack_rag.slack_api")
    @patch("common.slack.slack_rag.slack_rag.llm_client")
    def test_is_ready_after_build(self, mock_llm, mock_slack):
        mock_slack.read_channel_history.return_value = CHANNEL_MESSAGES[:2]
        mock_llm.generate.return_value = "summary"

        assert not slack_rag.is_ready("C_status")
        slack_rag.build("C_status")
        assert slack_rag.is_ready("C_status")

    @patch("common.slack.slack_rag.slack_rag.slack_api")
    @patch("common.slack.slack_rag.slack_rag.llm_client")
    def test_build_if_missing_skips_existing(self, mock_llm, mock_slack):
        mock_slack.read_channel_history.return_value = CHANNEL_MESSAGES[:2]
        mock_llm.generate.return_value = "summary"

        slack_rag.build("C_exists")
        mock_slack.read_channel_history.reset_mock()

        slack_rag.build_if_missing("C_exists")
        mock_slack.read_channel_history.assert_not_called()
