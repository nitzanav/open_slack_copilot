import json
from unittest.mock import patch

from common.tools import schedule_tool


class TestSchedulePromptToolSchema:
    def test_tool_definition_has_expected_shape(self):
        t = schedule_tool.SCHEDULE_PROMPT_TOOL
        assert t["type"] == "function"
        assert t["function"]["name"] == "schedule_prompt"
        params = t["function"]["parameters"]
        assert params["type"] == "object"
        assert set(params["required"]) == {"prompt", "cron"}

    def test_expires_in_days_is_optional(self):
        params = schedule_tool.SCHEDULE_PROMPT_TOOL["function"]["parameters"]
        assert "expires_in_days" not in params.get("required", [])


class TestHandleSchedulePromptCall:
    @patch("common.tools.prompt_scheduler.register_job_from_disk")
    @patch("common.tools.schedule_tool.get_invocation")
    def test_register_creates_files(self, mock_inv, mock_register, tmp_path, monkeypatch):
        monkeypatch.setattr(schedule_tool, "scheduled_prompts_root", lambda: tmp_path)
        mock_inv.return_value = {
            "channel_id": "C1",
            "thread_ts": "T1",
            "user_id": "U1",
        }
        args = json.dumps({"prompt": "Check emojis daily", "cron": "0 10 * * *"})
        out = json.loads(schedule_tool.handle_schedule_prompt_call(args))
        assert out["status"] == "scheduled"
        job_id = out["job_id"]
        base = tmp_path / job_id
        assert (base / "prompt.txt").read_text() == "Check emojis daily"
        meta = json.loads((base / "metadata.json").read_text())
        assert meta["thread_ts"] == "T1"
        assert meta["channel_id"] == "C1"
        assert "backoff_days" not in meta
        assert "skill_ref" not in meta
        mock_register.assert_called_once_with(job_id)

    @patch("common.tools.schedule_tool.get_invocation")
    def test_missing_prompt(self, mock_inv):
        mock_inv.return_value = {"channel_id": "C1", "thread_ts": "T1", "user_id": "U1"}
        out = json.loads(
            schedule_tool.handle_schedule_prompt_call(json.dumps({"cron": "0 10 * * *"}))
        )
        assert "error" in out

    @patch("common.tools.schedule_tool.get_invocation")
    def test_no_invocation_context(self, mock_inv):
        mock_inv.return_value = None
        out = json.loads(
            schedule_tool.handle_schedule_prompt_call(
                json.dumps({"prompt": "x", "cron": "0 10 * * *"})
            )
        )
        assert "error" in out

    @patch("common.tools.prompt_scheduler.register_job_from_disk")
    @patch("common.tools.schedule_tool.get_invocation")
    def test_expires_in_days_clamped(self, mock_inv, mock_register, tmp_path, monkeypatch):
        monkeypatch.setattr(schedule_tool, "scheduled_prompts_root", lambda: tmp_path)
        mock_inv.return_value = {"channel_id": "C1", "thread_ts": "T1", "user_id": "U1"}
        args = json.dumps({"prompt": "test", "cron": "0 10 * * *", "expires_in_days": 30})
        out = json.loads(schedule_tool.handle_schedule_prompt_call(args))
        assert out["status"] == "scheduled"
        meta = json.loads((tmp_path / out["job_id"] / "metadata.json").read_text())
        from datetime import datetime
        created = datetime.fromisoformat(meta["created_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(meta["expires_at"].replace("Z", "+00:00"))
        assert (expires - created).days <= 14
