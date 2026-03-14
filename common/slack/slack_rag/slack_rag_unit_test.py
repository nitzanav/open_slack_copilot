import time
from unittest.mock import patch, MagicMock

import pytest
from qdrant_client import QdrantClient

from common.rag import rag
from common.slack.slack_rag import slack_rag


@pytest.fixture(autouse=True)
def fresh_qdrant():
    rag.set_client(QdrantClient(location=":memory:"))
    slack_rag.reset_state()
    yield


CHANNEL_MESSAGES = [
    {"user": "U1", "text": f"Message about deployment issue {i}", "ts": f"170000{i:04d}.000"}
    for i in range(15)
]

ENGINEERING_MESSAGES = [
    {"user": "U2", "text": f"Engineering discussion about architecture {i}", "ts": f"180000{i:04d}.000"}
    for i in range(5)
]

PRODUCT_MESSAGES = [
    {"user": "U3", "text": f"Product roadmap item {i}", "ts": f"190000{i:04d}.000"}
    for i in range(5)
]


def _build_channel(channel_id, messages, mock_llm, mock_slack):
    mock_slack.read_channel_history.return_value = messages
    mock_llm.generate.return_value = "summary"
    slack_rag.build(channel_id)


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
        mock_llm.generate.side_effect = lambda p: f"Summary about deployment {hash(p) % 100}"

        slack_rag.build("C_many")
        results = slack_rag.query_channel("C_many", "deployment issue")
        assert len(results) == 10

    def test_query_empty_channel(self):
        results = slack_rag.query_channel("nonexistent", "anything")
        assert results == []


class TestCrossChannel:
    @patch("common.slack.slack_rag.slack_rag.slack_api")
    @patch("common.slack.slack_rag.slack_rag.llm_client")
    def test_query_cross_channel_merges_results(self, mock_llm, mock_slack):
        _build_channel("eng", ENGINEERING_MESSAGES, mock_llm, mock_slack)
        _build_channel("prod", PRODUCT_MESSAGES, mock_llm, mock_slack)
        _build_channel("support", CHANNEL_MESSAGES[:5], mock_llm, mock_slack)

        results = slack_rag.query_cross_channel(["eng", "prod", "support"], "architecture", top_k=10)
        assert len(results) == 10

    @patch("common.slack.slack_rag.slack_rag.slack_api")
    @patch("common.slack.slack_rag.slack_rag.llm_client")
    def test_cross_channel_excludes_current(self, mock_llm, mock_slack):
        _build_channel("eng", ENGINEERING_MESSAGES, mock_llm, mock_slack)
        _build_channel("support", CHANNEL_MESSAGES[:3], mock_llm, mock_slack)

        results = slack_rag.query_cross_channel(
            ["eng", "support"], "deployment", exclude_channel="support"
        )
        assert all(r.get("channel") != "support" for r in results)

    @patch("common.slack.slack_rag.slack_rag.slack_api")
    @patch("common.slack.slack_rag.slack_rag.llm_client")
    def test_missing_channel_detected(self, mock_llm, mock_slack):
        _build_channel("eng", ENGINEERING_MESSAGES, mock_llm, mock_slack)
        missing = slack_rag.missing_channels(["eng", "nonexistent"])
        assert missing == ["nonexistent"]

    def test_no_cross_channel_config_returns_empty(self):
        results = slack_rag.query_cross_channel([], "anything")
        assert results == []

    @patch("common.slack.slack_rag.slack_rag.slack_api")
    @patch("common.slack.slack_rag.slack_rag.llm_client")
    def test_build_all_missing(self, mock_llm, mock_slack):
        mock_slack.read_channel_history.return_value = ENGINEERING_MESSAGES[:2]
        mock_llm.generate.return_value = "summary"

        threads = slack_rag.build_all_missing(["ch_a", "ch_b"])
        for t in threads:
            t.join(timeout=5)

        assert slack_rag.is_ready("ch_a")
        assert slack_rag.is_ready("ch_b")

    @patch("common.slack.slack_rag.slack_rag.slack_api")
    @patch("common.slack.slack_rag.slack_rag.llm_client")
    def test_partial_failure(self, mock_llm, mock_slack):
        def side_effect(channel_id, oldest=0, limit=1000):
            if channel_id == "ch_fail":
                raise Exception("API error")
            return ENGINEERING_MESSAGES[:2]

        mock_slack.read_channel_history.side_effect = side_effect
        mock_llm.generate.return_value = "summary"

        threads = slack_rag.build_all_missing(["ch_ok", "ch_fail"])
        for t in threads:
            t.join(timeout=5)

        assert slack_rag.is_ready("ch_ok")
        assert not slack_rag.is_ready("ch_fail")


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


class TestIncrementalBuild:
    @patch("common.slack.slack_rag.slack_rag.slack_api")
    @patch("common.slack.slack_rag.slack_rag.llm_client")
    def test_second_build_only_summarizes_new_messages(self, mock_llm, mock_slack):
        mock_slack.read_channel_history.return_value = CHANNEL_MESSAGES[:3]
        mock_llm.generate.return_value = "summary"

        slack_rag.build("C_inc")
        assert mock_llm.generate.call_count == 3

        mock_llm.generate.reset_mock()
        new_msg = {"user": "U9", "text": "Brand new message", "ts": "199999999.000"}
        mock_slack.read_channel_history.return_value = CHANNEL_MESSAGES[:3] + [new_msg]

        slack_rag.build("C_inc")
        assert mock_llm.generate.call_count == 1

    @patch("common.slack.slack_rag.slack_rag.slack_api")
    @patch("common.slack.slack_rag.slack_rag.llm_client")
    def test_no_new_messages_skips_summarization(self, mock_llm, mock_slack):
        mock_slack.read_channel_history.return_value = CHANNEL_MESSAGES[:3]
        mock_llm.generate.return_value = "summary"

        slack_rag.build("C_skip")
        mock_llm.generate.reset_mock()

        slack_rag.build("C_skip")
        mock_llm.generate.assert_not_called()


class TestScheduler:
    @patch("common.slack.slack_rag.slack_rag.slack_api")
    @patch("common.slack.slack_rag.slack_rag.llm_client")
    def test_schedule_periodic_build_triggers(self, mock_llm, mock_slack):
        mock_slack.read_channel_history.return_value = CHANNEL_MESSAGES[:2]
        mock_llm.generate.return_value = "summary"

        t = slack_rag.schedule_periodic_build("C_sched", interval_seconds=0.2)
        time.sleep(0.5)
        slack_rag.stop_scheduler()

        assert mock_slack.read_channel_history.call_count >= 1
