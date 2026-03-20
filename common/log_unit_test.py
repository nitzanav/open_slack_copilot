from common.log import _sanitize


def test_sanitize_redacts_secrets():
    payload = {
        "token": "secret",
        "response_url": "https://hooks.slack.com/x",
        "channel": {"id": "C1", "name": "general"},
    }
    out = _sanitize(payload)
    assert out["token"] == "<redacted>"
    assert out["response_url"] == "<redacted>"
    assert out["channel"]["id"] == "C1"


def test_sanitize_truncates_long_strings():
    s = "x" * 2000
    out = _sanitize([s])
    assert isinstance(out[0], str)
    assert "truncated" in out[0]
    assert len(out[0]) < len(s)


def test_sanitize_replaces_blocks_with_count():
    msg = {"text": "hi", "blocks": [{"type": "rich_text"}]}
    out = _sanitize(msg)
    assert out["blocks"] == "<1 blocks>"


def test_sanitize_caps_long_lists():
    out = _sanitize(list(range(20)), max_list=3)
    assert len(out) == 4
    assert "more items" in out[-1]
