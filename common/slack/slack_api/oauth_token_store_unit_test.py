from pathlib import Path

import pytest

from common.data_layer import data_layer
from common.slack.slack_api import oauth_token_store


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_layer, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(oauth_token_store, "_owner_user_id_cache", None)


def _set_owner(monkeypatch: pytest.MonkeyPatch, token: str, resolved_user_id: str = "") -> None:
    if token:
        monkeypatch.setenv("SLACK_USER_TOKEN", token)
    else:
        monkeypatch.delenv("SLACK_USER_TOKEN", raising=False)
    monkeypatch.setattr(oauth_token_store, "_resolve_owner_user_id", lambda _t: resolved_user_id or None)


def test_saved_token_wins_over_owner_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_owner(monkeypatch, "xoxp-owner", resolved_user_id="U_OWNER")
    oauth_token_store.save_user_token("U_OWNER", "xoxp-saved")
    assert oauth_token_store.get_user_token("U_OWNER") == "xoxp-saved"


def test_owner_token_used_when_no_saved_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_owner(monkeypatch, "xoxp-owner", resolved_user_id="U_OWNER")
    assert oauth_token_store.get_user_token("U_OWNER") == "xoxp-owner"


def test_non_owner_user_with_no_saved_token_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_owner(monkeypatch, "xoxp-owner", resolved_user_id="U_OWNER")
    assert oauth_token_store.get_user_token("U_OTHER") is None


def test_unset_owner_config_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_owner(monkeypatch, "")
    assert oauth_token_store.get_user_token("U_ANY") is None


def test_empty_user_id_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_owner(monkeypatch, "xoxp-owner", resolved_user_id="U_OWNER")
    assert oauth_token_store.get_user_token("") is None


def test_owner_user_id_resolution_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    class _FakeClient:
        def __init__(self, token: str, ssl: object) -> None:  # noqa: A002
            pass

        def auth_test(self) -> dict[str, str]:
            calls["n"] += 1
            return {"user_id": "U_OWNER"}

    monkeypatch.setattr(oauth_token_store, "WebClient", _FakeClient)
    monkeypatch.setenv("SLACK_USER_TOKEN", "xoxp-owner")

    assert oauth_token_store.get_user_token("U_OWNER") == "xoxp-owner"
    assert oauth_token_store.get_user_token("U_OWNER") == "xoxp-owner"
    assert oauth_token_store.get_user_token("U_OTHER") is None
    assert calls["n"] == 1
