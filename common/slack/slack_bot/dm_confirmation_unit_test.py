from unittest.mock import patch

import pytest

from common.slack.slack_bot import dm_confirmation as dm


def _sample_blocks(message: str, uid: str = "U_TARGET") -> list[dict]:
    blocks = dm._build_confirmation_blocks("Alice", message, uid)
    return blocks


def test_parse_message_single_chunk():
    blocks = _sample_blocks("hello world")
    msg = dm.parse_message_from_confirmation_blocks(blocks)
    assert msg == "hello world"


def test_parse_message_multichunk():
    long_text = "x" * 4500
    blocks = _sample_blocks(long_text)
    msg = dm.parse_message_from_confirmation_blocks(blocks)
    assert msg == long_text
    assert len(blocks) == 4  # header + 2 body + actions


def test_build_blocks_rejects_overflow():
    too_long = "m" * (dm._MAX_BODY_BLOCKS * dm._PLAIN_CHUNK + 1)
    with pytest.raises(ValueError, match="too long"):
        dm._build_confirmation_blocks("Bob", too_long, "U1")


def test_handle_send_action_parses_and_sends():
    blocks = _sample_blocks("body text", uid="U_RECIPIENT")
    body = {
        "user": {"id": "U_CLICKER"},
        "actions": [{"value": "U_RECIPIENT"}],
        "message": {"blocks": blocks},
    }
    with patch("common.slack.slack_bot.dm_confirmation.slack_api") as api:
        result = dm.handle_send_action(body)
        assert result == "DM sent."
        api.send_dm.assert_called_once_with("U_RECIPIENT", "body text")
