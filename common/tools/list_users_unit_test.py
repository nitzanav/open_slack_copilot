import json
from unittest.mock import patch

from common.tools import list_users as lu


class TestListUsersToolSchema:
    def test_tool_name_and_required_param(self):
        t = lu.LIST_USERS_TOOL
        assert t["function"]["name"] == "list_users"
        assert t["function"]["parameters"]["required"] == ["query"]


class TestHandleListUsersCall:
    @patch("common.tools.list_users.slack_directory_rag")
    def test_ok(self, mock_rag):
        mock_rag.search.return_value = [
            {
                "id": "U1",
                "name": "Alice",
                "handle": "alice",
                "email": "a@x.com",
                "title": "Dev",
            },
        ]
        out = json.loads(lu.handle_list_users_call(json.dumps({"query": "alice"})))
        assert out["query"] == "alice"
        assert len(out["users"]) == 1
        assert out["users"][0]["id"] == "U1"
        mock_rag.build_if_missing.assert_called_once()
        mock_rag.search.assert_called_once_with("alice", kind="user", top_k=5)

    def test_missing_query(self):
        out = json.loads(lu.handle_list_users_call("{}"))
        assert "error" in out

    @patch("common.tools.list_users.slack_directory_rag")
    def test_top_k_clamped(self, mock_rag):
        mock_rag.search.return_value = []
        lu.handle_list_users_call(json.dumps({"query": "x", "top_k": 999}))
        mock_rag.search.assert_called_once_with("x", kind="user", top_k=50)
