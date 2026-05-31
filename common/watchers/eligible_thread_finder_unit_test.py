from unittest.mock import MagicMock, patch

from common.watchers.eligible_thread_finder import _slack_oldest_ts, iter_recent_thread_ids


def _page(messages, cursor=None):
    res = {"messages": messages}
    if cursor:
        res["response_metadata"] = {"next_cursor": cursor}
    return res


def test_yields_distinct_thread_roots_in_channel_history_order():
    client = MagicMock()
    client.conversations_history.return_value = _page([
        {"ts": "100.0"},
        {"ts": "101.0", "thread_ts": "100.0"},
        {"ts": "200.0"},
    ])
    with patch("common.watchers.eligible_thread_finder.slack_api.get_client", return_value=client):
        assert list(iter_recent_thread_ids("C1", 0.0)) == ["100.0", "200.0"]


def test_paginates_until_no_cursor():
    client = MagicMock()
    client.conversations_history.side_effect = [
        _page([{"ts": "10.0"}], cursor="abc"),
        _page([{"ts": "20.0"}]),
    ]
    with patch("common.watchers.eligible_thread_finder.slack_api.get_client", return_value=client):
        out = list(iter_recent_thread_ids("C1", 0.0))
        assert out == ["10.0", "20.0"]
        assert client.conversations_history.call_count == 2


def test_passes_oldest_to_slack():
    client = MagicMock()
    client.conversations_history.return_value = _page([])
    with patch("common.watchers.eligible_thread_finder.slack_api.get_client", return_value=client):
        list(iter_recent_thread_ids("C1", 12345.5))
    kwargs = client.conversations_history.call_args.kwargs
    assert kwargs["channel"] == "C1"
    assert kwargs["oldest"] == "12345.500000"
    assert kwargs["limit"] == 200


def test_slack_oldest_ts_avoids_float_string_noise():
    assert _slack_oldest_ts(1779042892.281862) == "1779042892.281862"
    assert _slack_oldest_ts(12345.5) == "12345.500000"
