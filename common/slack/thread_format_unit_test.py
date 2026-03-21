from unittest.mock import patch

from common.slack.thread_format import format_slack_thread_for_prompt


@patch("common.slack.thread_format.slack_api")
def test_slack_thread_includes_reaction_lines(mock_api):
    mock_api.get_channel_prefixed_name.return_value = "#general"
    mock_api.get_user_display_name.side_effect = lambda uid: {"U1": "Alice", "U2": "Bob"}.get(
        uid, uid
    )
    messages = [
        {
            "user": "U1",
            "ts": "1700000001.000001",
            "text": "Hello",
            "reactions": [
                {"name": "thumbsup", "users": ["U2"], "count": 1},
            ],
        },
    ]
    out = format_slack_thread_for_prompt(
        messages,
        channel_id="C1",
        thread_ts="1700000001.123",
        channel_display_name="#general",
    )
    assert "Channel id: C1" in out
    assert "<@U1>: Alice" in out
    assert "[2023-11-14 22:13] <@U1>: Hello" in out
    assert "reaction :thumbsup: by <@U2>" in out
