from unittest.mock import patch

import pytest

pytestmark = pytest.mark.filterwarnings(
    "ignore:There is no current event loop:DeprecationWarning"
)

from common.llm.llm_client.llm_client import ToolCallRecord
from common.slack import agent_log


@pytest.fixture
def agent_root(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_log, "AGENT_LOGS_DIR", tmp_path)
    monkeypatch.setattr(agent_log, "GLOBAL_LOG", tmp_path / "llm_actions.log")
    return tmp_path


def test_append_and_read_roundtrip(agent_root):
    agent_log.append_entry(
        {
            "timestamp": "2026-03-14T16:26:00+00:00",
            "channel": "C1",
            "thread_ts": "1.2",
            "trigger": "slash_command",
            "action": "suggested_draft",
            "summary": "wrote shorter draft",
        }
    )
    rows = agent_log.read_recent_for_thread("C1", "1.2", 10)
    assert len(rows) == 1
    assert rows[0]["summary"] == "wrote shorter draft"
    g = (agent_root / "llm_actions.log").read_text()
    assert "C1" in g


def test_read_skips_bad_json(agent_root):
    p = agent_log.thread_log_path("C1", "1.0")
    p.parent.mkdir(parents=True)
    p.write_text('{"a":1}\nnot json\n{"b":2}\n', encoding="utf-8")
    rows = agent_log.read_recent_for_thread("C1", "1.0", 10)
    assert len(rows) == 2


def test_format_agent_log_section_compact():
    text = agent_log.format_agent_log_section(
        [
            {
                "timestamp": "2026-03-14T16:26:00+00:00",
                "trigger": "message_shortcut_revise",
                "action": "suggested_draft",
                "summary": "wrote shorter draft",
            }
        ]
    )
    assert "## Agent log" in text
    assert "message shortcut revise" in text
    assert "suggested draft" in text
    assert "C0" not in text


@patch.object(agent_log.llm_client, "generate", return_value="Suggested consulting IT first")
def test_summarize_uses_llm(mock_gen):
    long_draft = "Try IT. " * 20  # >= 100 chars so summarizer LLM is used
    out = agent_log.summarize_copilot_run(
        trigger="message_shortcut",
        action="suggested_draft",
        user_text="help",
        final_text=long_draft,
        tool_trace=[],
    )
    assert "consulting" in out.lower()
    mock_gen.assert_called_once()


@patch.object(agent_log.llm_client, "generate")
def test_summarize_short_final_skips_llm(mock_gen):
    out = agent_log.summarize_copilot_run(
        trigger="app_mention",
        action="suggested_draft",
        user_text="hi",
        final_text="Short reply here.",
        tool_trace=[],
    )
    assert out == "Short reply here."
    mock_gen.assert_not_called()


def test_tool_trace_for_record():
    rows = agent_log.tool_trace_for_record(
        [
            ToolCallRecord("schedule_prompt", '{"status":"scheduled"}'),
        ]
    )
    assert rows == [{"name": "schedule_prompt", "result_preview": '{"status":"scheduled"}'}]


def test_format_agent_log_section_includes_tool_names():
    text = agent_log.format_agent_log_section(
        [
            {
                "timestamp": "2026-03-14T16:26:00+00:00",
                "trigger": "app_mention",
                "action": "suggested_draft",
                "summary": "Scheduled hourly follow-up.",
                "tools": [
                    {"name": "schedule_prompt", "result_preview": '{"status":"scheduled"}'}
                ],
            }
        ]
    )
    assert "| tools: schedule_prompt" in text


def test_summarize_fallback_schedule_tool():
    out = agent_log.summarize_copilot_run(
        trigger="slash_command",
        action="suggested_draft",
        user_text="",
        final_text="",
        tool_trace=[ToolCallRecord("schedule_prompt", '{"status":"scheduled"}')],
    )
    assert "Scheduled" in out or "scheduled" in out
