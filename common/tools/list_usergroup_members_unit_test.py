import json
from unittest.mock import patch

from slack_sdk.errors import SlackApiError

from common.tools import list_usergroup_members as lugm


class TestListUsergroupMembersToolSchema:
    def test_tool_name_and_required_param(self):
        t = lugm.LIST_USERGROUP_MEMBERS_TOOL
        assert t["function"]["name"] == "list_usergroup_members"
        req = t["function"]["parameters"]["required"]
        assert req == ["usergroup"]


class TestHandleListUsergroupMembersCall:
    @patch("common.tools.list_usergroup_members.slack_api.list_usergroup_members")
    def test_ok(self, mock_list):
        mock_list.return_value = ("S0123", ["U1", "U2"])
        out = json.loads(
            lugm.handle_list_usergroup_members_call(
                json.dumps({"usergroup": "backend-team"})
            )
        )
        assert out == {"usergroup_id": "S0123", "user_ids": ["U1", "U2"]}
        mock_list.assert_called_once_with("backend-team")

    def test_missing_usergroup(self):
        out = json.loads(lugm.handle_list_usergroup_members_call("{}"))
        assert "error" in out

    @patch("common.tools.list_usergroup_members.slack_api.list_usergroup_members")
    def test_resolve_error(self, mock_list):
        mock_list.side_effect = ValueError("Could not resolve user group: 'nope'")
        out = json.loads(
            lugm.handle_list_usergroup_members_call(
                json.dumps({"usergroup": "nope"})
            )
        )
        assert out["error"] == "Could not resolve user group: 'nope'"

    @patch("common.tools.list_usergroup_members.slack_api.list_usergroup_members")
    def test_slack_api_error(self, mock_list):
        err = SlackApiError(message="api error", response={"error": "not_authed"})
        mock_list.side_effect = err
        out = json.loads(
            lugm.handle_list_usergroup_members_call(
                json.dumps({"usergroup": "S01"})
            )
        )
        assert out["error"] == "not_authed"
