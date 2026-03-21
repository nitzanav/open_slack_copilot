import time
from unittest.mock import patch

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


def _prep_slack_mock(mock_slack):
    mock_slack.get_user_display_name.return_value = ""


def _build_channel(channel_id, messages, mock_slack):
    _prep_slack_mock(mock_slack)
    mock_slack.read_channel_history.return_value = messages
    slack_rag.build(channel_id)


class TestBuild:
    @patch("common.slack.slack_rag.slack_rag.slack_api")
    def test_build_fetches_from_checkpoint(self, mock_slack):
        _prep_slack_mock(mock_slack)
        mock_slack.read_channel_history.return_value = CHANNEL_MESSAGES[:3]

        slack_rag.build("C1", checkpoint_seconds=30 * 86400)

        call_args = mock_slack.read_channel_history.call_args
        assert call_args[0][0] == "C1"
        assert call_args[1]["oldest"] > 0

    @patch("common.slack.slack_rag.slack_rag.slack_api")
    def test_build_indexes_each_message(self, mock_slack):
        _prep_slack_mock(mock_slack)
        mock_slack.read_channel_history.return_value = CHANNEL_MESSAGES[:5]

        slack_rag.build("C2")
        assert slack_rag.inspect_channel("C2")["count"] == 5

    @patch("common.slack.slack_rag.slack_rag.slack_api")
    def test_build_stores_from_name(self, mock_slack):
        _prep_slack_mock(mock_slack)
        mock_slack.get_user_display_name.side_effect = lambda uid: f"user_{uid}"
        mock_slack.read_channel_history.return_value = CHANNEL_MESSAGES[:2]

        slack_rag.build("C_names")
        results = slack_rag.query_channel("C_names", "deployment", top_k=10)
        assert results[0].get("from_name") == "user_U1"

    @patch("common.slack.slack_rag.slack_rag.slack_api")
    def test_build_inserts_into_qdrant(self, mock_slack):
        _prep_slack_mock(mock_slack)
        mock_slack.read_channel_history.return_value = CHANNEL_MESSAGES[:3]

        slack_rag.build("C3")

        results = slack_rag.query_channel("C3", "deployment")
        assert len(results) == 3

    @patch("common.slack.slack_rag.slack_rag.slack_api")
    def test_build_failure_releases_lock(self, mock_slack):
        _prep_slack_mock(mock_slack)
        mock_slack.read_channel_history.side_effect = Exception("API error")

        with pytest.raises(Exception):
            slack_rag.build("C_fail")

        lock = rag.acquire_lock("C_fail")
        assert lock.acquire(timeout=0.1)
        lock.release()


class TestIndexSubtypeFilter:
    @patch("common.slack.slack_rag.slack_rag.slack_api")
    def test_skips_system_subtypes(self, mock_slack):
        _prep_slack_mock(mock_slack)
        mock_slack.read_channel_history.return_value = [
            {"user": "U1", "text": "real post", "ts": "1700000001.000"},
            {
                "user": "U2",
                "subtype": "channel_join",
                "text": "<@U2> has joined the channel",
                "ts": "1700000002.000",
            },
            {"user": "U1", "text": "another post", "ts": "1700000003.000"},
        ]
        slack_rag.build("C_filter")
        assert slack_rag.inspect_channel("C_filter")["count"] == 2

    @patch("common.slack.slack_rag.slack_rag.slack_api")
    def test_allows_file_share_and_bot_message(self, mock_slack):
        _prep_slack_mock(mock_slack)
        mock_slack.read_channel_history.return_value = [
            {
                "user": "U1",
                "subtype": "file_share",
                "text": "See attached log",
                "ts": "1700000001.000",
            },
            {
                "subtype": "bot_message",
                "text": "CI passed",
                "ts": "1700000002.000",
                "bot_id": "B1",
            },
        ]
        slack_rag.build("C_allow")
        assert slack_rag.inspect_channel("C_allow")["count"] == 2

    @patch("common.slack.slack_rag.slack_rag.slack_api")
    def test_appends_reactions_to_indexed_text(self, mock_slack):
        _prep_slack_mock(mock_slack)
        mock_slack.read_channel_history.return_value = [
            {
                "user": "U1",
                "text": "ship it",
                "ts": "1700000001.000",
                "reactions": [
                    {"name": "thumbsup", "count": 2, "users": ["U1", "U2"]},
                    {"name": "rocket", "count": 1, "users": ["U3"]},
                ],
            },
        ]
        slack_rag.build("C_rx")
        docs = slack_rag.inspect_channel("C_rx")["documents"]
        assert len(docs) == 1
        assert "[Reactions:" in docs[0]["text"]
        assert ":rocket: ×1" in docs[0]["text"]
        assert ":thumbsup: ×2" in docs[0]["text"]


class TestQuery:
    @patch("common.slack.slack_rag.slack_rag.slack_api")
    def test_query_returns_top_10(self, mock_slack):
        _prep_slack_mock(mock_slack)
        mock_slack.read_channel_history.return_value = CHANNEL_MESSAGES

        slack_rag.build("C_many")
        results = slack_rag.query_channel("C_many", "deployment issue")
        assert len(results) == 10

    def test_query_empty_channel(self):
        results = slack_rag.query_channel("nonexistent", "anything")
        assert results == []


class TestCrossChannel:
    @patch("common.slack.slack_rag.slack_rag.slack_api")
    def test_query_cross_channel_merges_results(self, mock_slack):
        _build_channel("eng", ENGINEERING_MESSAGES, mock_slack)
        _build_channel("prod", PRODUCT_MESSAGES, mock_slack)
        _build_channel("support", CHANNEL_MESSAGES[:5], mock_slack)

        results = slack_rag.query_cross_channel(["eng", "prod", "support"], "architecture", top_k=10)
        assert len(results) == 10

    @patch("common.slack.slack_rag.slack_rag.slack_api")
    def test_cross_channel_excludes_current(self, mock_slack):
        _build_channel("eng", ENGINEERING_MESSAGES, mock_slack)
        _build_channel("support", CHANNEL_MESSAGES[:3], mock_slack)

        results = slack_rag.query_cross_channel(
            ["eng", "support"], "deployment", exclude_channel="support"
        )
        assert all(r.get("channel") != "support" for r in results)

    @patch("common.slack.slack_rag.slack_rag.slack_api")
    def test_missing_channel_detected(self, mock_slack):
        _build_channel("eng", ENGINEERING_MESSAGES, mock_slack)
        missing = slack_rag.missing_channels(["eng", "nonexistent"])
        assert missing == ["nonexistent"]

    def test_no_cross_channel_config_returns_empty(self):
        results = slack_rag.query_cross_channel([], "anything")
        assert results == []

    @patch("common.slack.slack_rag.slack_rag.slack_api")
    def test_build_all_missing(self, mock_slack):
        _prep_slack_mock(mock_slack)
        mock_slack.read_channel_history.return_value = ENGINEERING_MESSAGES[:2]

        threads = slack_rag.build_all_missing(["ch_a", "ch_b"])
        for t in threads:
            t.join(timeout=5)

        assert slack_rag.is_ready("ch_a")
        assert slack_rag.is_ready("ch_b")

    @patch("common.slack.slack_rag.slack_rag.slack_api")
    def test_partial_failure(self, mock_slack):
        _prep_slack_mock(mock_slack)

        def side_effect(channel_id, oldest=0, limit=1000):
            if channel_id == "ch_fail":
                raise Exception("API error")
            return ENGINEERING_MESSAGES[:2]

        mock_slack.read_channel_history.side_effect = side_effect

        threads = slack_rag.build_all_missing(["ch_ok", "ch_fail"])
        for t in threads:
            t.join(timeout=5)

        assert slack_rag.is_ready("ch_ok")
        assert not slack_rag.is_ready("ch_fail")


class TestStatus:
    @patch("common.slack.slack_rag.slack_rag.slack_api")
    def test_is_ready_after_build(self, mock_slack):
        _prep_slack_mock(mock_slack)
        mock_slack.read_channel_history.return_value = CHANNEL_MESSAGES[:2]

        assert not slack_rag.is_ready("C_status")
        slack_rag.build("C_status")
        assert slack_rag.is_ready("C_status")

    @patch("common.slack.slack_rag.slack_rag.slack_api")
    def test_build_if_missing_skips_existing(self, mock_slack):
        _prep_slack_mock(mock_slack)
        mock_slack.read_channel_history.return_value = CHANNEL_MESSAGES[:2]

        slack_rag.build("C_exists")
        mock_slack.read_channel_history.reset_mock()

        slack_rag.build_if_missing("C_exists")
        mock_slack.read_channel_history.assert_not_called()


class TestIncrementalBuild:
    @patch("common.slack.slack_rag.slack_rag.slack_api")
    def test_second_build_only_indexes_new_messages(self, mock_slack):
        _prep_slack_mock(mock_slack)
        mock_slack.read_channel_history.return_value = CHANNEL_MESSAGES[:3]

        slack_rag.build("C_inc")
        assert slack_rag.inspect_channel("C_inc")["count"] == 3

        new_msg = {"user": "U9", "text": "Brand new message", "ts": "199999999.000"}
        mock_slack.read_channel_history.return_value = CHANNEL_MESSAGES[:3] + [new_msg]

        slack_rag.build("C_inc")
        assert slack_rag.inspect_channel("C_inc")["count"] == 4

    @patch("common.slack.slack_rag.slack_rag.slack_api")
    def test_no_new_messages_skips_index_update(self, mock_slack):
        _prep_slack_mock(mock_slack)
        mock_slack.read_channel_history.return_value = CHANNEL_MESSAGES[:3]

        slack_rag.build("C_skip")
        assert slack_rag.inspect_channel("C_skip")["count"] == 3

        mock_slack.read_channel_history.reset_mock()
        slack_rag.build("C_skip")
        assert slack_rag.inspect_channel("C_skip")["count"] == 3


class TestFormatRagText:
    @patch("common.slack.slack_rag.slack_rag.slack_api")
    def test_format_rag_context_block_matches_plain_text_shape(self, mock_slack):
        mock_slack.get_user_display_name.return_value = ""
        results = [
            {
                "from": "U0ALHV1GDDK",
                "from_name": "Info",
                "ts": "1773505612.000000",
                "text": "The make run does not work",
            },
            {
                "from": "U0AMFJ2AVME",
                "from_name": "Hola",
                "ts": "1773505723.000000",
                "text": "now make test does not work. what to do now?",
            },
        ]
        text = slack_rag.format_rag_context_block(
            "12345678",
            "C0ALHSXRDU5",
            results,
            channel_display_name="#all-elias",
        )
        assert text == (
            "Channel id: 12345678\n"
            "Channel name: #all-elias\n"
            "Thread id: C0ALHSXRDU5\n"
            "Users:\n"
            "  <@U0ALHV1GDDK>: Info\n"
            "  <@U0AMFJ2AVME>: Hola\n"
            "\n"
            "[2026-03-14 16:26] <@U0ALHV1GDDK>: The make run does not work\n"
            "[2026-03-14 16:28] <@U0AMFJ2AVME>: now make test does not work. what to do now?"
        )

    @patch("common.slack.slack_rag.slack_rag.slack_api")
    def test_format_cross_channel_rag_text_groups_channels(self, mock_slack):
        mock_slack.get_channel_prefixed_name.side_effect = lambda cid: f"#{cid}"
        mock_slack.get_user_display_name.return_value = ""
        results = [
            {"channel": "C2", "from": "U2", "ts": "2.0", "text": "second"},
            {"channel": "C1", "from": "U1", "ts": "1.0", "text": "first"},
        ]
        text = slack_rag.format_cross_channel_rag_text(results)
        assert text.index("Channel id: C1") < text.index("Channel id: C2")
        assert "[1970-01-01 00:00] <@U1>: first" in text
        assert "[1970-01-01 00:00] <@U2>: second" in text


class TestScheduler:
    @patch("common.slack.slack_rag.slack_rag.slack_api")
    def test_schedule_periodic_build_triggers(self, mock_slack):
        _prep_slack_mock(mock_slack)
        mock_slack.read_channel_history.return_value = CHANNEL_MESSAGES[:2]

        t = slack_rag.schedule_periodic_build("C_sched", interval_seconds=0.2)
        time.sleep(0.5)
        slack_rag.stop_scheduler()

        assert mock_slack.read_channel_history.call_count >= 1
