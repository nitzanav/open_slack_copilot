"""Unit tests for user group resolution (slack_api)."""

from unittest.mock import MagicMock, patch

from common.slack.slack_api import slack_api


class TestResolveUsergroupId:
    def test_raw_id(self):
        assert slack_api.resolve_usergroup_id("S061KE5N") == "S061KE5N"

    def test_subteam_mention_with_label(self):
        assert (
            slack_api.resolve_usergroup_id("hey <!subteam^S061KE5N|backend-team>")
            == "S061KE5N"
        )

    def test_subteam_mention_without_label(self):
        assert slack_api.resolve_usergroup_id("<!subteam^SZZZ>") == "SZZZ"

    def test_unknown_returns_none(self):
        with patch.object(slack_api, "get_client") as mock_gc:
            mock_gc.return_value.usergroups_list.return_value = {
                "usergroups": [],
                "response_metadata": {},
            }
            assert slack_api.resolve_usergroup_id("missing-group") is None

    def test_resolve_by_handle(self):
        client = MagicMock()
        client.usergroups_list.return_value = {
            "usergroups": [
                {
                    "id": "S111",
                    "handle": "backend-team",
                    "name": "Backend",
                },
            ],
            "response_metadata": {},
        }
        with patch.object(slack_api, "get_client", return_value=client):
            assert slack_api.resolve_usergroup_id("@backend-team") == "S111"
            assert slack_api.resolve_usergroup_id("backend-team") == "S111"

    def test_resolve_by_name(self):
        client = MagicMock()
        client.usergroups_list.return_value = {
            "usergroups": [
                {"id": "S222", "handle": "be", "name": "Backend Crew"},
            ],
            "response_metadata": {},
        }
        with patch.object(slack_api, "get_client", return_value=client):
            assert slack_api.resolve_usergroup_id("Backend Crew") == "S222"


class TestListUsergroupMembers:
    def test_returns_ids(self):
        client = MagicMock()
        client.usergroups_list.return_value = {
            "usergroups": [{"id": "S1", "handle": "g"}],
            "response_metadata": {},
        }
        client.usergroups_users_list.return_value = {"users": ["U1", "U2"]}
        with patch.object(slack_api, "get_client", return_value=client):
            ugid, ids = slack_api.list_usergroup_members("g")
        assert ugid == "S1"
        assert ids == ["U1", "U2"]
        client.usergroups_users_list.assert_called_once_with(usergroup="S1")
