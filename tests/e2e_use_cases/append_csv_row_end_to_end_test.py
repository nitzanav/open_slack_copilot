"""End-to-end test: run_react_loop with fake LLM calling append_csv_row -> CSV under data root.

Run with step logs: ``pytest tests/e2e_use_cases/append_csv_row_end_to_end_test.py -v -s``
"""

from __future__ import annotations

import csv
import json
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import pytest

import common.tools.append_csv_row  # noqa: F401 — registers tool
from common.llm.llm_apis.types import ChatCompletionTurn, NormalizedToolCall
from common.log import get_test_logger
from common.slack.copilot_pipeline import run_react_loop
from tests.e2e_use_cases.llm_fake_backend import FakeCompletionBackend, assert_llm_input_token_budget

C_TEST = "C0ALHSXRDU5"
U_USER1 = "U0AMFJ2AVME"
TS_ROOT = "1779450059.378599"
SKILL_ID = "general_instruction"
ACTION_TS = "2026-05-22T10:00:00+00:00"

_e2e_log = get_test_logger("e2e")


def _log(msg: str) -> None:
    _e2e_log.info("[e2e] %s", msg)


def _log_ok(label: str) -> None:
    _e2e_log.info("[e2e] ok: %s", label)


def _append_csv_row_args() -> str:
    return json.dumps({"sentiment": "positive", "topic": "e2e"}, separators=(",", ":"))


def _scripted_llm_turns() -> list[ChatCompletionTurn]:
    return [
        ChatCompletionTurn(
            "",
            (
                NormalizedToolCall(
                    "tc_csv_1",
                    "append_csv_row",
                    _append_csv_row_args(),
                ),
            ),
        ),
        ChatCompletionTurn("Logged one row to the skill CSV.", ()),
    ]


@dataclass
class AppendCsvRowE2EContext:
    data_root: Path
    mock_slack: MagicMock
    fake_backend: FakeCompletionBackend
    mock_pd: MagicMock
    mock_rag: MagicMock


def build_append_csv_row_e2e_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> AppendCsvRowE2EContext:
    _log("build context")
    from config.config import settings

    original = settings.get("data_layer", {})
    settings.set("data_layer", {**original, "root": str(tmp_path)})

    skill_text = (
        Path(__file__).resolve().parents[2]
        / "skill_examples"
        / "general_instruction"
        / "SKILL.md"
    ).read_text()

    mock_slack = MagicMock()
    mock_slack.read_thread.return_value = [
        {
            "user": U_USER1,
            "type": "message",
            "ts": TS_ROOT,
            "text": "Please log this thread to CSV.",
            "team": "T0ALHSXBC1K",
            "thread_ts": TS_ROOT,
        },
    ]
    mock_slack.get_bot_user_id.return_value = "U0AMFLB44JC"
    mock_slack.get_channel_prefixed_name.return_value = "#e2e-test"

    fake_backend = FakeCompletionBackend(_scripted_llm_turns())

    mock_pd = MagicMock()
    mock_pd.select_skills.return_value = [skill_text]
    mock_pd.get_default_instruction.return_value = ""

    mock_rag = MagicMock()
    mock_rag.is_ready.return_value = True
    mock_rag.query_channel.return_value = []
    mock_rag.missing_channels.return_value = []
    mock_rag.query_cross_channel.return_value = []

    ctx = AppendCsvRowE2EContext(
        data_root=tmp_path,
        mock_slack=mock_slack,
        fake_backend=fake_backend,
        mock_pd=mock_pd,
        mock_rag=mock_rag,
    )
    _log_ok("context ready")
    return ctx


@contextmanager
def patched_append_csv_row_e2e(ctx: AppendCsvRowE2EContext) -> Iterator[None]:
    with (
        patch("common.slack.copilot_pipeline.slack_api", ctx.mock_slack),
        patch("common.tools.append_csv_row.slack_api", ctx.mock_slack),
        patch("common.slack.copilot_pipeline.slack_rag", ctx.mock_rag),
        patch("common.slack.copilot_pipeline.progressive_disclosure", ctx.mock_pd),
        patch(
            "common.llm.llm_client.llm_client.get_completion_backend",
            lambda: ctx.fake_backend,
        ),
    ):
        yield


class TestAppendCsvRowEndToEnd:
    def test_react_loop_append_csv_row_writes_skill_csv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        ctx = build_append_csv_row_e2e_context(tmp_path, monkeypatch)
        with patched_append_csv_row_e2e(ctx):
            _log("run_react_loop with append_csv_row")
            result = run_react_loop(
                C_TEST,
                TS_ROOT,
                U_USER1,
                "log sentiment and topic to csv",
                channel_name="#e2e-test",
                thread_messages=ctx.mock_slack.read_thread.return_value,
                skill_id=SKILL_ID,
                action_ts=ACTION_TS,
            )
            assert "Logged one row" in result.text
            _log_ok("react loop finished")

        csv_path = ctx.data_root / "data" / f"{SKILL_ID}.csv"
        assert csv_path.is_file(), "CSV created under temp data root"
        with csv_path.open(newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        assert rows[0][:4] == ["skill_id", "channel_name", "thread_ts", "action_ts"]
        assert rows[1][0] == SKILL_ID
        assert rows[1][1] == "#e2e-test"
        assert rows[1][2] == TS_ROOT
        assert rows[1][3] == ACTION_TS
        assert rows[1][-2:] == ["positive", "e2e"]
        _log_ok("csv row contents")

        assert len(ctx.fake_backend.complete_calls) == 2
        assert not ctx.fake_backend._turns
        _log_ok("scripted turns consumed")
        assert_llm_input_token_budget(
            ctx.fake_backend, log_ok=_log_ok, log_info=_log,
        )
