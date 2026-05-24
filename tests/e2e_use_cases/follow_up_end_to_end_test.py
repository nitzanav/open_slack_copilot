"""End-to-end test: @CoPilot follow up -> schedule_prompt -> sync scheduled run -> confirm -> post thread.

APScheduler is bypassed by patching ``register_job_from_disk`` to call ``run_scheduled_prompt``
immediately (production DEBUG mode uses a 5s DateTrigger instead).

Run with step logs: ``pytest tests/e2e_use_cases/follow_up_end_to_end_test.py -v -s``
(App ``@log`` trace is DEBUG and hidden in tests; step lines use INFO on ``open_slack_copilot.test.e2e``.)
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import pytest

import common.tools.schedule_tool as schedule_tool_module
import common.tools.send_thread_reply_as_app  # noqa: F401 — registers tool
from common.log import get_test_logger
from common.llm.llm_apis.types import ChatCompletionTurn, NormalizedToolCall
from tests.e2e_use_cases.llm_fake_backend import FakeCompletionBackend, assert_llm_input_token_budget
from common.slack.slack_bot import tool_confirmation as tc
from common.tools.prompt_scheduler import prompt_scheduler as sched_mod

# Imports register tools used by dispatch
import common.tools.send_thread_reply_on_behalf_of_requester  # noqa: F401

C_TEST = "C0ALHSXRDU5"
U_USER1 = "U0AMFJ2AVME"
U_USER2 = "U0ALHV1GDDK"
U_BOT = "U0AMFLB44JC"
TS_ROOT = "1779443464.746199"
TS_MENTION = "1779443475.352209"

ROOT_TEXT = (
    f"<@{U_USER2}> please confirm the cupcake order spreadsheet by 3pm. "
    "React with :cupcake: when the rows look correct."
)

SCHEDULE_PROMPT_BODY = (
    f"Follow-up: In #{C_TEST}, thread "
    f"https://slack.com/archives/{C_TEST}/p1779443464746199, verify the bakery order. "
    f"Watcher: <@{U_USER2}>. Done when: :cupcake: reaction is on the root message.\n"
    f"1. Check whether <@{U_USER2}> added the :cupcake: reaction.\n"
    "2. If not, call `send_thread_reply_as_app` ONCE with a friendly nudge. "
    "Do not loop per user."
)

REMINDER_MESSAGE = (
    f"Friendly nudge: <@{U_USER2}>, please double-check the cupcake order sheet "
    "and add a :cupcake: reaction when it looks good. Thanks!"
)

FINAL_TEXT_APP_MENTION = (
    f"I scheduled an hourly check for <@{U_USER2}> to add a :cupcake: on the order thread. "
    "Reminders stop after 1 day."
)

FINAL_TEXT_SCHEDULED = (
    f"The scheduled run queued a thread reminder for <@{U_USER2}> to confirm the cupcake "
    "order spreadsheet and add a :cupcake: reaction when the rows look correct."
)

_e2e_log = get_test_logger("e2e")


def _log(msg: str) -> None:
    _e2e_log.info("[e2e] %s", msg)


def _log_ok(label: str) -> None:
    _e2e_log.info("[e2e] ok: %s", label)


@dataclass
class FollowUpE2EContext:
    scheduled_root: Path
    mock_slack: MagicMock
    fake_backend: FakeCompletionBackend
    mock_generate: MagicMock
    app_mention_event: dict[str, Any]
    mock_pd: MagicMock
    mock_rag: MagicMock


def _schedule_prompt_args() -> str:
    return json.dumps(
        {
            "prompt": SCHEDULE_PROMPT_BODY,
            "cron": "0 * * * *",
            "expires_in_days": 1,
        },
        separators=(",", ":"),
    )


def _send_thread_as_app_args() -> str:
    return json.dumps({"message": REMINDER_MESSAGE}, separators=(",", ":"))


def _scripted_llm_turns() -> list[ChatCompletionTurn]:
    return [
        ChatCompletionTurn(
            "",
            (
                NormalizedToolCall(
                    "tc_schedule_1",
                    "schedule_prompt",
                    _schedule_prompt_args(),
                ),
            ),
        ),
        ChatCompletionTurn(FINAL_TEXT_APP_MENTION, ()),
        ChatCompletionTurn(
            "",
            (
                NormalizedToolCall(
                    "tc_reply_as_app_1",
                    "send_thread_reply_as_app",
                    _send_thread_as_app_args(),
                ),
            ),
        ),
        ChatCompletionTurn(FINAL_TEXT_SCHEDULED, ()),
    ]


def _thread_messages_fixture() -> list[dict]:
    return [
        {
            "user": U_USER1,
            "type": "message",
            "ts": TS_ROOT,
            "text": ROOT_TEXT,
            "team": "T0ALHSXBC1K",
            "thread_ts": TS_ROOT,
            "reply_count": 1,
            "blocks": [{"type": "rich_text", "block_id": "b1"}],
        },
        {
            "user": U_USER1,
            "type": "message",
            "ts": TS_MENTION,
            "text": f"<@{U_BOT}> follow up",
            "team": "T0ALHSXBC1K",
            "thread_ts": TS_ROOT,
            "parent_user_id": U_USER1,
            "blocks": [{"type": "rich_text", "block_id": "b2"}],
        },
    ]


def _app_mention_event_fixture() -> dict[str, Any]:
    return {
        "type": "app_mention",
        "user": U_USER1,
        "ts": TS_MENTION,
        "text": f"<@{U_BOT}> follow up",
        "team": "T0ALHSXBC1K",
        "thread_ts": TS_ROOT,
        "channel": C_TEST,
    }


def _confirm_button_value_from_blocks(blocks: list[dict]) -> str:
    for block in blocks:
        if block.get("type") != "actions":
            continue
        for el in block.get("elements") or []:
            if el.get("action_id") == tc.ACTION_TOOL_CONFIRM:
                return str(el.get("value") or "")
    raise AssertionError("confirm button not found in blocks")


def build_follow_up_e2e_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> FollowUpE2EContext:
    _log("build context")
    scheduled_root = tmp_path / "scheduled_prompts"
    scheduled_root.mkdir(parents=True, exist_ok=True)
    drafts_dir = tmp_path / "tool_confirm_drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    agent_logs = tmp_path / "agent_logs"
    agent_logs.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        schedule_tool_module, "scheduled_prompts_root", lambda: scheduled_root,
    )
    monkeypatch.setattr(sched_mod, "scheduled_prompts_root", lambda: scheduled_root)
    monkeypatch.setattr(tc, "_TOOL_CONFIRM_DRAFT_DIR", drafts_dir)

    import common.slack.agent_log as agent_log_mod

    monkeypatch.setattr(agent_log_mod, "AGENT_LOGS_DIR", agent_logs)

    skill_text = (
        Path(__file__).resolve().parents[2]
        / "skill_examples"
        / "follow_up"
        / "SKILL.md"
    ).read_text()

    mock_slack = MagicMock()
    mock_slack.read_thread.return_value = _thread_messages_fixture()
    mock_slack.get_bot_user_id.return_value = U_BOT

    fake_backend = FakeCompletionBackend(_scripted_llm_turns())
    mock_generate = MagicMock(
        return_value="Scheduled hourly cupcake-order follow-up.",
    )

    def sync_register(job_id: str) -> None:
        _log(f"scheduler sync run job {job_id}")
        sched_mod.run_scheduled_prompt(job_id)

    mock_pd = MagicMock()
    mock_pd.select_skills.return_value = [skill_text]
    mock_pd.get_default_instruction.return_value = ""

    mock_rag = MagicMock()
    mock_rag.is_ready.return_value = True
    mock_rag.query_channel.return_value = []
    mock_rag.missing_channels.return_value = []
    mock_rag.query_cross_channel.return_value = []

    monkeypatch.setattr(
        "common.tools.prompt_scheduler.register_job_from_disk",
        sync_register,
    )

    ctx = FollowUpE2EContext(
        scheduled_root=scheduled_root,
        mock_slack=mock_slack,
        fake_backend=fake_backend,
        mock_generate=mock_generate,
        app_mention_event=_app_mention_event_fixture(),
        mock_pd=mock_pd,
        mock_rag=mock_rag,
    )
    _log_ok("context ready")
    return ctx


@contextmanager
def patched_follow_up_e2e(ctx: FollowUpE2EContext) -> Iterator[None]:
    with (
        patch("common.slack.copilot_pipeline.slack_api", ctx.mock_slack),
        patch("common.slack.slack_bot.slack_listener_with_threads.slack_api", ctx.mock_slack),
        patch("common.slack.slack_bot.tool_confirmation.slack_api", ctx.mock_slack),
        patch("common.slack.copilot_user_notify.slack_api", ctx.mock_slack),
        patch("common.tools.send_thread_reply_as_app.slack_api", ctx.mock_slack),
        patch("common.slack.copilot_pipeline.slack_rag", ctx.mock_rag),
        patch("common.slack.copilot_pipeline.progressive_disclosure", ctx.mock_pd),
        patch(
            "common.llm.llm_client.llm_client.get_completion_backend",
            lambda: ctx.fake_backend,
        ),
        patch("common.slack.agent_log.llm_client.generate", ctx.mock_generate),
    ):
        yield


def trigger_app_mention_follow_up(ctx: FollowUpE2EContext) -> None:
    _log("slack app_mention follow up")
    from common.slack.slack_bot.slack_listener_with_threads import register_copilot_app_mention
    from core.slack_bot import _handle_copilot

    app = MagicMock()
    register_copilot_app_mention(app, _handle_copilot, bot_user_id=U_BOT)
    mention_fn = app.event.return_value.call_args[0][0]
    mention_fn(event=ctx.app_mention_event)
    _log_ok("app_mention handled")


def build_confirm_action_body(confirm_value: str) -> dict[str, Any]:
    return {
        "user": {"id": U_USER1},
        "channel": {"id": C_TEST},
        "actions": [{"value": confirm_value, "action_id": tc.ACTION_TOOL_CONFIRM}],
        "container": {"thread_ts": TS_ROOT},
        "message": {"blocks": []},
    }


def simulate_send_thread_reply_button_click(
    ctx: FollowUpE2EContext, confirm_value: str,
) -> None:
    _log("slack tool_confirm_action send thread reply")
    result = tc.handle_confirm_action(build_confirm_action_body(confirm_value))
    assert result == "Posted to thread.", "confirm handler returns Posted to thread."
    _log_ok("confirm posted")


def assert_llm_agent_loop_ran_four_times(ctx: FollowUpE2EContext) -> None:
    assert ctx.fake_backend.complete_calls, "LLM complete was called"
    assert len(ctx.fake_backend.complete_calls) == 4, "LLM agent loop: 4 complete calls"
    _log_ok("LLM complete x4")


def assert_scripted_llm_turns_fully_consumed(ctx: FollowUpE2EContext) -> None:
    assert not ctx.fake_backend._turns, "all scripted LLM turns used"
    _log_ok("scripted turns consumed")


def assert_copilot_run_summarized_via_generate_twice(ctx: FollowUpE2EContext) -> None:
    assert ctx.mock_generate.call_count == 2, "agent_log summarize: 2 generate calls"
    _log_ok("generate x2")


def assert_draft_prompt_includes_task_and_follow_up(ctx: FollowUpE2EContext) -> None:
    first_system = ctx.fake_backend.complete_calls[0][0]["content"]
    assert ROOT_TEXT in first_system, "system prompt includes root task text"
    assert "cupcake" in first_system.lower(), "system prompt includes follow up instruction"
    _log_ok("prompt has order task + follow up")


def assert_schedule_prompt_job_written_to_disk(ctx: FollowUpE2EContext) -> None:
    job_dirs = [p for p in ctx.scheduled_root.iterdir() if p.is_dir()]
    assert len(job_dirs) == 1, "one scheduled job directory"
    job_dir = job_dirs[0]
    meta = json.loads((job_dir / "metadata.json").read_text())
    assert meta["channel_id"] == C_TEST, "job meta channel_id"
    assert meta["thread_ts"] == TS_ROOT, "job meta thread_ts"
    assert meta["user_id"] == U_USER1, "job meta user_id"
    prompt_txt = (job_dir / "prompt.txt").read_text()
    assert U_USER2 in prompt_txt or f"<@{U_USER2}>" in prompt_txt, "job prompt mentions target user"
    _log_ok("schedule job on disk")


def assert_reminder_confirm_ui_shown_once(ctx: FollowUpE2EContext) -> str:
    ctx.mock_slack.send_ephemeral_blocks.assert_called_once()
    blocks = ctx.mock_slack.send_ephemeral_blocks.call_args[0][4]
    confirm_value = _confirm_button_value_from_blocks(blocks)
    _log_ok("confirm ephemeral blocks x1")
    return confirm_value


def assert_thread_not_posted_before_user_confirms(ctx: FollowUpE2EContext) -> None:
    ctx.mock_slack.post_thread_message_as_app.assert_not_called()
    _log_ok("no thread post before confirm")


def assert_user_confirm_posts_reminder_as_app(
    ctx: FollowUpE2EContext, confirm_value: str,
) -> None:
    simulate_send_thread_reply_button_click(ctx, confirm_value)
    ctx.mock_slack.post_thread_message_as_app.assert_called_once_with(
        C_TEST, TS_ROOT, REMINDER_MESSAGE,
    )
    _log_ok("post_thread_message_as_app with reminder")


@pytest.fixture(autouse=True)
def _shutdown_scheduler():
    yield
    sched_mod.shutdown_scheduler()
    sched_mod._scheduler = None  # noqa: SLF001


class TestFollowUpEndToEnd:
    def test_app_mention_schedules_then_reminder_posts_after_confirm(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        ctx = build_follow_up_e2e_context(tmp_path, monkeypatch)
        with patched_follow_up_e2e(ctx):
            trigger_app_mention_follow_up(ctx)
            assert_llm_agent_loop_ran_four_times(ctx)
            assert_scripted_llm_turns_fully_consumed(ctx)
            assert_copilot_run_summarized_via_generate_twice(ctx)
            assert_draft_prompt_includes_task_and_follow_up(ctx)
            assert_llm_input_token_budget(
                ctx.fake_backend, log_ok=_log_ok, log_info=_log,
            )
            assert_schedule_prompt_job_written_to_disk(ctx)
            confirm_value = assert_reminder_confirm_ui_shown_once(ctx)
            assert_thread_not_posted_before_user_confirms(ctx)
            assert_user_confirm_posts_reminder_as_app(ctx, confirm_value)
