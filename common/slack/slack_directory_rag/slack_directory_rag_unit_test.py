import time
from unittest.mock import MagicMock, patch

import pytest
from qdrant_client import QdrantClient

from common.rag import rag
from common.slack.slack_directory_rag import slack_directory_rag


@pytest.fixture(autouse=True)
def fresh_qdrant():
    rag.set_client(QdrantClient(location=":memory:"))
    yield


def _client_with_users_and_groups():
    client = MagicMock()

    def users_list(**kwargs):
        return {
            "members": [
                {
                    "id": "U_ALICE",
                    "deleted": False,
                    "is_bot": False,
                    "real_name": "Alice Smith",
                    "name": "alice",
                    "profile": {
                        "display_name": "Ali",
                        "email": "alice@example.com",
                        "title": "Engineer",
                    },
                },
                {
                    "id": "U_BOB",
                    "deleted": False,
                    "is_bot": False,
                    "real_name": "Robert",
                    "name": "bob",
                    "profile": {"display_name": "", "email": ""},
                },
            ],
            "response_metadata": {},
        }

    def usergroups_list(**kwargs):
        return {
            "usergroups": [
                {
                    "id": "S_ENG",
                    "handle": "engineering",
                    "name": "Engineering",
                    "description": "All engineers",
                },
            ],
            "response_metadata": {},
        }

    client.users_list.side_effect = users_list
    client.usergroups_list.side_effect = usergroups_list
    return client


class TestBuildAndSearch:
    @patch("common.slack.slack_directory_rag.slack_directory_rag.slack_api.get_client")
    def test_build_indexes_users(self, mock_get_client):
        mock_get_client.return_value = _client_with_users_and_groups()
        slack_directory_rag.build()
        hits = slack_directory_rag.search("alice smith", kind="user", top_k=10)
        ids = {h.get("id") for h in hits}
        assert "U_ALICE" in ids

    @patch("common.slack.slack_directory_rag.slack_directory_rag.slack_api.get_client")
    def test_search_usergroup_kind(self, mock_get_client):
        mock_get_client.return_value = _client_with_users_and_groups()
        slack_directory_rag.build()
        hits = slack_directory_rag.search("engineering team", kind="usergroup", top_k=10)
        assert any(h.get("id") == "S_ENG" for h in hits)

    @patch("common.slack.slack_directory_rag.slack_directory_rag.slack_api.get_client")
    def test_usergroups_list_typeerror_retries_without_include_users(self, mock_get_client):
        client = MagicMock()
        client.users_list.return_value = {"members": [], "response_metadata": {}}

        def ug_list(**kwargs):
            if "include_users" in kwargs:
                raise TypeError("unexpected keyword")
            return {"usergroups": [], "response_metadata": {}}

        client.usergroups_list.side_effect = ug_list
        mock_get_client.return_value = client
        slack_directory_rag.build()
        assert slack_directory_rag.is_ready()
        assert client.usergroups_list.call_count >= 2


class TestScheduler:
    @patch("common.slack.slack_directory_rag.slack_directory_rag.slack_api.get_client")
    def test_schedule_daily_refresh_triggers_build(self, mock_get_client):
        mock_get_client.return_value = _client_with_users_and_groups()
        slack_directory_rag.schedule_daily_refresh(interval_seconds=0.2)
        time.sleep(0.55)
        slack_directory_rag.stop_scheduler()
        assert mock_get_client.return_value.users_list.call_count >= 2
