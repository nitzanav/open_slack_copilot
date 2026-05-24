"""End-to-end: fake LLM calls list_users to resolve a person via directory RAG."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest

import common.tools.list_users  # noqa: F401 — registers tool
from common.llm.llm_apis.types import ChatCompletionTurn, NormalizedToolCall
from common.log import get_test_logger
from common.slack.copilot_pipeline import run_react_loop
from tests.e2e_use_cases.llm_fake_backend import FakeCompletionBackend, assert_llm_input_token_budget

C_TEST = "C0ALHSXRDU5"
U_USER1 = "U0AMFJ2AVME"
U_ALICE = "U_ALICE_E2E"
TS_ROOT = "1779450059.378599"
SKILL_ID = "general_instruction"

_e2e_log = get_test_logger("e2e")


def _log(msg: str) -> None:
    _e2e_log.info("[e2e] %s", msg)


def _log_ok(label: str) -> None:
    _e2e_log.info("[e2e] ok: %s", label)


def _list_users_args() -> str:
    return json.dumps({"query": "Alice Smith"}, separators=(",", ":"))


def _scripted_llm_turns() -> list[ChatCompletionTurn]:
    return [
        ChatCompletionTurn(
            "",
            (
                NormalizedToolCall(
                    "tc_list_users_1",
                    "list_users",
                    _list_users_args(),
                ),
            ),
        ),
        ChatCompletionTurn(f"Resolved Alice to {U_ALICE}.", ()),
    ]


@dataclass
class DirectoryRagE2EContext:
    mock_slack: MagicMock
    fake_backend: FakeCompletionBackend
    mock_pd: MagicMock
    mock_rag: MagicMock
    mock_directory_rag: MagicMock


def build_directory_rag_e2e_context() -> DirectoryRagE2EContext:
    _log("build context")
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
            "text": "Who is Alice Smith on the team?",
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

    mock_directory_rag = MagicMock()
    mock_directory_rag.search.return_value = [
        {
            "id": U_ALICE,
            "name": "Alice Smith",
            "handle": "alice",
            "email": "alice@example.com",
            "title": "Engineer",
        },
    ]

    ctx = DirectoryRagE2EContext(
        mock_slack=mock_slack,
        fake_backend=fake_backend,
        mock_pd=mock_pd,
        mock_rag=mock_rag,
        mock_directory_rag=mock_directory_rag,
    )
    _log_ok("context ready")
    return ctx


@contextmanager
def patched_directory_rag_e2e(ctx: DirectoryRagE2EContext) -> Iterator[None]:
    with (
        patch("common.slack.copilot_pipeline.slack_api", ctx.mock_slack),
        patch("common.slack.copilot_pipeline.slack_rag", ctx.mock_rag),
        patch("common.slack.copilot_pipeline.progressive_disclosure", ctx.mock_pd),
        patch("common.tools.list_users.slack_directory_rag", ctx.mock_directory_rag),
        patch(
            "common.llm.llm_client.llm_client.get_completion_backend",
            lambda: ctx.fake_backend,
        ),
    ):
        yield


class TestDirectoryRagEndToEnd:
    def test_react_loop_list_users_resolves_person(self):
        ctx = build_directory_rag_e2e_context()
        with patched_directory_rag_e2e(ctx):
            _log("run_react_loop with list_users")
            result = run_react_loop(
                C_TEST,
                TS_ROOT,
                U_USER1,
                "resolve Alice Smith to her user id",
                channel_name="#e2e-test",
                thread_messages=ctx.mock_slack.read_thread.return_value,
                skill_id=SKILL_ID,
            )
            assert U_ALICE in result.text
            _log_ok("react loop finished")

        ctx.mock_directory_rag.build_if_missing.assert_called_once()
        ctx.mock_directory_rag.search.assert_called_once_with(
            "Alice Smith", kind="user", top_k=5,
        )
        tool_names = [getattr(r, "name", None) for r in result.tool_trace]
        assert "list_users" in tool_names
        _log_ok("list_users invoked")

        assert len(ctx.fake_backend.complete_calls) == 2
        assert not ctx.fake_backend._turns
        _log_ok("scripted turns consumed")
        assert_llm_input_token_budget(
            ctx.fake_backend, log_ok=_log_ok, log_info=_log,
        )
