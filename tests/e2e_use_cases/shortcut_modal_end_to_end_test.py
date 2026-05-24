"""E2E: message shortcut ``slack_copilot_follow_up`` opens modal and forces one skill load on submit.

Run with step logs: ``pytest tests/e2e_use_cases/shortcut_modal_end_to_end_test.py -v -s``
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import pytest

from common.log import get_test_logger
from common.llm.llm_apis.types import ChatCompletionTurn, NormalizedToolCall
from tests.e2e_use_cases.llm_fake_backend import FakeCompletionBackend, assert_llm_input_token_budget

import common.tools.send_thread_reply_on_behalf_of_requester  # noqa: F401 — registers tool

C_TEST = "C0ALHSXRDU5"
U_USER1 = "U0AMFJ2AVME"
U_BOT = "U0AMFLB44JC"
TS_ROOT = "1779450059.378599"
TS_MSG = "1779450071.334449"

FOLLOW_UP_SKILL_TEXT = (
    Path(__file__).resolve().parents[2]
    / "skill_examples"
    / "follow_up"
    / "SKILL.md"
).read_text()

TRIGGER_INSTRUCTION = 'user asked to trigger skill "Follow Up".'

_e2e_log = get_test_logger("e2e")


def _log(msg: str) -> None:
    _e2e_log.info("[e2e] %s", msg)


def _log_ok(label: str) -> None:
    _e2e_log.info("[e2e] ok: %s", label)


def _on_behalf_args(message: str) -> str:
    return json.dumps({"message": message}, separators=(",", ":"))


def _scripted_llm_turns() -> list[ChatCompletionTurn]:
    return [
        ChatCompletionTurn(
            "",
            (
                NormalizedToolCall(
                    "tc_follow_up",
                    "send_thread_reply_on_behalf_of_requester",
                    _on_behalf_args("Follow-up draft for the thread."),
                ),
            ),
        ),
        ChatCompletionTurn("Scheduled follow-up check drafted.", ()),
    ]


def _thread_messages_fixture() -> list[dict]:
    return [
        {
            "user": U_USER1,
            "type": "message",
            "ts": TS_ROOT,
            "text": "Please review the RFC by Friday @bob",
            "team": "T0ALHSXBC1K",
            "thread_ts": TS_ROOT,
            "reply_count": 1,
        },
        {
            "user": U_USER1,
            "type": "message",
            "ts": TS_MSG,
            "text": "Bump for visibility",
            "team": "T0ALHSXBC1K",
            "thread_ts": TS_ROOT,
            "parent_user_id": U_USER1,
        },
    ]


@dataclass
class ShortcutModalE2EContext:
    mock_slack: MagicMock
    fake_backend: FakeCompletionBackend
    mock_pd: MagicMock
    mock_rag: MagicMock


def build_shortcut_modal_e2e_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> ShortcutModalE2EContext:
    _log("build context")
    drafts_dir = tmp_path / "tool_confirm_drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    agent_logs = tmp_path / "agent_logs"
    agent_logs.mkdir(parents=True, exist_ok=True)

    import common.slack.slack_bot.tool_confirmation as tc

    monkeypatch.setattr(tc, "_TOOL_CONFIRM_DRAFT_DIR", drafts_dir)

    import common.slack.agent_log as agent_log_mod

    monkeypatch.setattr(agent_log_mod, "AGENT_LOGS_DIR", agent_logs)

    mock_slack = MagicMock()
    mock_slack.read_thread.return_value = _thread_messages_fixture()
    mock_slack.get_bot_user_id.return_value = U_BOT
    mock_slack.get_channel_prefixed_name.return_value = C_TEST

    fake_backend = FakeCompletionBackend(_scripted_llm_turns())

    mock_pd = MagicMock()
    mock_pd.select_skills.return_value = []
    mock_pd.get_default_instruction.return_value = ""
    mock_pd.load_forced_skill.return_value = ("follow_up", FOLLOW_UP_SKILL_TEXT)

    mock_rag = MagicMock()
    mock_rag.is_ready.return_value = True
    mock_rag.query_channel.return_value = []
    mock_rag.missing_channels.return_value = []
    mock_rag.query_cross_channel.return_value = []

    ctx = ShortcutModalE2EContext(
        mock_slack=mock_slack,
        fake_backend=fake_backend,
        mock_pd=mock_pd,
        mock_rag=mock_rag,
    )
    _log_ok("context ready")
    return ctx


@contextmanager
def patched_shortcut_modal_e2e(ctx: ShortcutModalE2EContext) -> Iterator[None]:
    with (
        patch("common.slack.copilot_pipeline.slack_api", ctx.mock_slack),
        patch("common.slack.slack_bot.slack_listener_with_threads.slack_api", ctx.mock_slack),
        patch("common.slack.copilot_user_notify.slack_api", ctx.mock_slack),
        patch(
            "common.tools.send_thread_reply_on_behalf_of_requester.slack_api",
            ctx.mock_slack,
        ),
        patch("common.slack.copilot_pipeline.slack_rag", ctx.mock_rag),
        patch("common.slack.copilot_pipeline.progressive_disclosure", ctx.mock_pd),
        patch(
            "common.llm.llm_client.llm_client.get_completion_backend",
            lambda: ctx.fake_backend,
        ),
    ):
        yield


def _make_listener_decorator():
    def decorator(fn):
        decorator.registered = fn
        return fn
    return decorator


def trigger_follow_up_shortcut_and_submit(
    ctx: ShortcutModalE2EContext,
    mock_load_forced: MagicMock,
) -> None:
    from common.slack.slack_bot.slack_listener_with_threads import (
        BLOCK_SHORTCUT_INSTRUCTION,
        ACTION_SHORTCUT_INSTRUCTION_TEXT,
        register_copilot_shortcut,
    )
    from core.slack_bot import _handle_copilot

    _log("slack message shortcut follow_up")
    app = MagicMock()
    shortcut_dec = _make_listener_decorator()
    view_dec = _make_listener_decorator()
    app.shortcut.return_value = shortcut_dec
    app.view.return_value = view_dec
    register_copilot_shortcut(app, _handle_copilot)
    shortcut_fn = shortcut_dec.registered
    modal_fn = view_dec.registered

    client = MagicMock()
    shortcut = {
        "callback_id": "slack_copilot_follow_up",
        "channel": {"id": C_TEST, "name": "general"},
        "user": {"id": U_USER1},
        "message": {"ts": TS_MSG, "thread_ts": TS_ROOT},
        "trigger_id": "trigger-follow-up",
    }
    shortcut_fn(ack=MagicMock(), shortcut=shortcut, client=client)

    view = client.views_open.call_args[1]["view"]
    instr = next(
        b for b in view["blocks"] if b.get("block_id") == BLOCK_SHORTCUT_INSTRUCTION
    )
    assert instr["element"]["initial_value"] == TRIGGER_INSTRUCTION
    _log_ok("modal initial instruction")

    mock_load_forced.reset_mock()

    body = {
        "view": {
            "private_metadata": view["private_metadata"],
            "state": {
                "values": {
                    BLOCK_SHORTCUT_INSTRUCTION: {
                        ACTION_SHORTCUT_INSTRUCTION_TEXT: {
                            "value": TRIGGER_INSTRUCTION,
                        },
                    },
                },
            },
        },
    }
    modal_fn(ack=MagicMock(), body=body, _client=MagicMock())
    mock_load_forced.assert_called_once_with("follow_up")
    _log_ok("submit forced skill load once")


def assert_forced_skill_in_prompt(ctx: ShortcutModalE2EContext) -> None:
    assert ctx.fake_backend.complete_calls, "expected LLM completion"
    prompt = ctx.fake_backend.complete_calls[0]
    sys_msg = next(m for m in prompt if m.get("role") == "system")
    content = sys_msg.get("content") or ""
    assert "Follow Up" in content or "follow up" in content.lower()
    assert TRIGGER_INSTRUCTION in content
    _log_ok("forced skill in system prompt")


class TestShortcutModalEndToEnd:
    def test_follow_up_shortcut_modal_and_single_forced_load(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        ctx = build_shortcut_modal_e2e_context(tmp_path, monkeypatch)
        with patched_shortcut_modal_e2e(ctx):
            with patch(
                "common.slack.copilot_pipeline.load_forced_skill",
                side_effect=lambda folder: ("follow_up", FOLLOW_UP_SKILL_TEXT),
            ) as mock_load_forced:
                with patch(
                    "common.slack.slack_bot.slack_listener_with_threads"
                    ".load_forced_skill",
                    side_effect=lambda folder: ("follow_up", FOLLOW_UP_SKILL_TEXT),
                ):
                    trigger_follow_up_shortcut_and_submit(ctx, mock_load_forced)
            assert_forced_skill_in_prompt(ctx)
            assert_llm_input_token_budget(
                ctx.fake_backend,
                log_ok=_log_ok,
                log_info=_log,
            )
            peak = max(ctx.fake_backend.input_token_counts)
            _log(f"peak input tokens={peak}")
