"""End-to-end test: @CoPilot summarize -> confirm UI -> revise -> confirm -> post on behalf.

OAuth is mocked so ``post_thread_message_on_behalf_of_requester`` succeeds (production may
surface ``OAuthNotConnectedError`` until user OAuth is connected).

Run with step logs: ``pytest tests/e2e_use_cases/summarize_revise_end_to_end_test.py -v -s``
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
from common.slack.mrkdwn_convert import to_slack_mrkdwn
from common.slack.slack_bot import tool_confirmation as tc

import common.tools.send_thread_reply_on_behalf_of_requester  # noqa: F401 — registers tool

C_TEST = "C0ALHSXRDU5"
U_USER1 = "U0AMFJ2AVME"
U_BOT = "U0AMFLB44JC"
TS_ROOT = "1779450059.378599"
TS_MENTION = "1779450071.334449"

ROOT_TEXT = (
    "Team offsite planning notes:\n"
    "```- Book venue with AV and breakout rooms\n"
    "- Send attendee survey by Friday\n"
    "- Catering: vegetarian default, nut-free dessert option\n"
    "- Draft day-one agenda (keynote, workshops, retro)\n"
    "\nLater\n"
    "- Swag mockups\n"
    "- Photographer\n"
    "\nDropped\n"
    "- Outdoor-only venue (weather risk)```"
)

FIRST_SUMMARY_DRAFT = (
    "Offsite planning snapshot:\n\n"
    "### This week\n"
    "- **Venue**: Reserve space with AV and breakout rooms.\n"
    "- **Survey**: Attendee preferences due Friday.\n"
    "- **Catering**: Vegetarian default; include a nut-free dessert.\n"
    "- **Agenda**: Day-one outline — keynote, workshops, retro.\n\n"
    "### Later\n"
    "- Swag mockups and event photographer.\n\n"
    "### Dropped\n"
    "- Outdoor-only venue because of weather risk."
)

REVISED_SUMMARY_DRAFT = (
    "Offsite — short version:\n\n"
    "### This week\n"
    "- **Venue & AV**\n"
    "- **Friday survey**\n"
    "- **Catering** (veg + nut-free dessert)\n"
    "- **Day-one agenda**\n\n"
    "### Later\n"
    "- Swag, photographer\n\n"
    "### Dropped\n"
    "- Outdoor-only venue"
)

FINAL_TEXT_APP_MENTION = (
    "I drafted a full offsite planning summary for the thread, including venue, survey, "
    "catering, agenda, later items, and what we dropped. Please confirm if you want that "
    "version posted for everyone in the thread."
)

FINAL_TEXT_REVISE = (
    "I drafted a shorter offsite summary with one line per section. Please review the "
    "condensed version and confirm if you want it posted in the thread for the team."
)

REVISE_INSTRUCTION = "Tighten it — one line per bucket, no sub-bullets."

_e2e_log = get_test_logger("e2e")


def _log(msg: str) -> None:
    _e2e_log.info("[e2e] %s", msg)


def _log_ok(label: str) -> None:
    _e2e_log.info("[e2e] ok: %s", label)


@dataclass
class SummarizeReviseE2EContext:
    mock_slack: MagicMock
    fake_backend: FakeCompletionBackend
    mock_generate: MagicMock
    app_mention_event: dict[str, Any]
    mock_pd: MagicMock
    mock_rag: MagicMock


def _on_behalf_args(message: str) -> str:
    return json.dumps({"message": message}, separators=(",", ":"))


def _scripted_llm_turns() -> list[ChatCompletionTurn]:
    return [
        ChatCompletionTurn(
            "",
            (
                NormalizedToolCall(
                    "tc_on_behalf_1",
                    "send_thread_reply_on_behalf_of_requester",
                    _on_behalf_args(FIRST_SUMMARY_DRAFT),
                ),
            ),
        ),
        ChatCompletionTurn(FINAL_TEXT_APP_MENTION, ()),
        ChatCompletionTurn(
            "",
            (
                NormalizedToolCall(
                    "tc_on_behalf_2",
                    "send_thread_reply_on_behalf_of_requester",
                    _on_behalf_args(REVISED_SUMMARY_DRAFT),
                ),
            ),
        ),
        ChatCompletionTurn(FINAL_TEXT_REVISE, ()),
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
            "text": f"<@{U_BOT}> summarize",
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
        "text": f"<@{U_BOT}> summarize",
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


def _draft_text_from_blocks(blocks: list[dict]) -> str:
    for block in blocks:
        block_id = str(block.get("block_id") or "")
        if not block_id.startswith(tc.BLOCK_BODY_PREFIX):
            continue
        text = (block.get("text") or {}).get("text") or ""
        if text:
            return text
    raise AssertionError("draft body not found in blocks")


def build_summarize_revise_e2e_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> SummarizeReviseE2EContext:
    _log("build context")
    drafts_dir = tmp_path / "tool_confirm_drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    agent_logs = tmp_path / "agent_logs"
    agent_logs.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(tc, "_TOOL_CONFIRM_DRAFT_DIR", drafts_dir)

    import common.slack.agent_log as agent_log_mod

    monkeypatch.setattr(agent_log_mod, "AGENT_LOGS_DIR", agent_logs)

    skill_text = (
        Path(__file__).resolve().parents[2]
        / "skill_examples"
        / "reply"
        / "general_instruction"
        / "SKILL.md"
    ).read_text()

    mock_slack = MagicMock()
    mock_slack.read_thread.return_value = _thread_messages_fixture()
    mock_slack.get_bot_user_id.return_value = U_BOT
    mock_slack.get_channel_prefixed_name.return_value = C_TEST

    fake_backend = FakeCompletionBackend(_scripted_llm_turns())
    mock_generate = MagicMock(
        side_effect=[
            "Drafted offsite summary for thread reply.",
            "Drafted short offsite summary after revise.",
        ],
    )

    mock_pd = MagicMock()
    mock_pd.select_skills.return_value = [skill_text]
    mock_pd.get_default_instruction.return_value = ""

    mock_rag = MagicMock()
    mock_rag.is_ready.return_value = True
    mock_rag.query_channel.return_value = []
    mock_rag.missing_channels.return_value = []
    mock_rag.query_cross_channel.return_value = []

    ctx = SummarizeReviseE2EContext(
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
def patched_summarize_revise_e2e(ctx: SummarizeReviseE2EContext) -> Iterator[None]:
    with (
        patch("common.slack.copilot_pipeline.slack_api", ctx.mock_slack),
        patch("common.slack.slack_bot.slack_listener_with_threads.slack_api", ctx.mock_slack),
        patch("common.slack.slack_bot.tool_confirmation.slack_api", ctx.mock_slack),
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
        patch("common.slack.agent_log.llm_client.generate", ctx.mock_generate),
    ):
        yield


def trigger_app_mention_summarize(ctx: SummarizeReviseE2EContext) -> None:
    _log("slack app_mention summarize")
    from common.slack.slack_bot.slack_listener_with_threads import register_copilot_app_mention
    from core.slack_bot import _handle_copilot

    app = MagicMock()
    register_copilot_app_mention(app, _handle_copilot, bot_user_id=U_BOT)
    mention_fn = app.event.return_value.call_args[0][0]
    mention_fn(event=ctx.app_mention_event)
    _log_ok("app_mention handled")


def trigger_revise_after_first_draft(
    ctx: SummarizeReviseE2EContext, first_draft: str,
) -> None:
    _log("slack tool_confirm_revise rerun copilot")
    from common.slack.slack_bot.react_runner import run_react_and_confirm

    user_text = tc._compose_tool_revise_user_text(
        REVISE_INSTRUCTION, first_draft, include_text=True,
    )
    run_react_and_confirm(
        C_TEST,
        TS_ROOT,
        U_USER1,
        U_USER1,
        user_text,
        context_kind="thread",
        channel_name=C_TEST,
        copilot_trigger="tool_confirm_revise",
        copilot_action="confirmation_required_tool",
    )
    _log_ok("revise copilot run done")


def build_confirm_action_body(confirm_value: str) -> dict[str, Any]:
    return {
        "user": {"id": U_USER1},
        "channel": {"id": C_TEST},
        "actions": [{"value": confirm_value, "action_id": tc.ACTION_TOOL_CONFIRM}],
        "container": {"thread_ts": TS_ROOT},
        "message": {"blocks": []},
    }


def simulate_send_thread_reply_button_click(
    ctx: SummarizeReviseE2EContext, confirm_value: str,
) -> None:
    _log("slack tool_confirm_action send thread reply")
    result = tc.handle_confirm_action(build_confirm_action_body(confirm_value))
    assert result == "Posted to thread.", "confirm handler returns Posted to thread."
    _log_ok("confirm posted")


def assert_llm_agent_loop_ran_four_times(ctx: SummarizeReviseE2EContext) -> None:
    assert len(ctx.fake_backend.complete_calls) == 4, "LLM agent loop: 4 complete calls"
    _log_ok("LLM complete x4")


def assert_scripted_llm_turns_fully_consumed(ctx: SummarizeReviseE2EContext) -> None:
    assert not ctx.fake_backend._turns, "all scripted LLM turns used"
    _log_ok("scripted turns consumed")


def assert_copilot_run_summarized_via_generate_twice(ctx: SummarizeReviseE2EContext) -> None:
    assert ctx.mock_generate.call_count == 2, "agent_log summarize: 2 generate calls"
    _log_ok("generate x2")


def assert_draft_prompt_includes_thread_and_summarize(ctx: SummarizeReviseE2EContext) -> None:
    first_system = ctx.fake_backend.complete_calls[0][0]["content"]
    assert "offsite planning" in first_system.lower(), "system prompt includes thread notes"
    assert "summarize" in first_system.lower(), "system prompt includes summarize instruction"
    _log_ok("prompt has thread + summarize")


def assert_first_confirm_ui_shows_long_summary(ctx: SummarizeReviseE2EContext) -> str:
    assert ctx.mock_slack.send_ephemeral_blocks.call_count >= 1, "confirm UI shown"
    blocks = ctx.mock_slack.send_ephemeral_blocks.call_args_list[0][0][4]
    draft = _draft_text_from_blocks(blocks)
    assert "Offsite planning snapshot" in draft, "first draft is long summary"
    assert "nut-free dessert" in draft, "first draft has detailed bullets"
    _log_ok("first confirm ephemeral")
    return draft


def _system_prompt_text(messages: list[dict]) -> str:
    return str(next(m.get("content") or "" for m in messages if m.get("role") == "system"))


def assert_revise_rerun_uses_proposed_text(ctx: SummarizeReviseE2EContext) -> None:
    revise_system = _system_prompt_text(ctx.fake_backend.complete_calls[2])
    assert to_slack_mrkdwn(FIRST_SUMMARY_DRAFT)[:80] in revise_system, (
        "revise system prompt includes first draft"
    )
    assert REVISE_INSTRUCTION in revise_system, "revise system prompt includes instruction"
    _log_ok("revise prompt wired")


def assert_second_confirm_ui_shows_brief_summary(ctx: SummarizeReviseE2EContext) -> str:
    assert ctx.mock_slack.send_ephemeral_blocks.call_count == 2, "two confirm UIs"
    blocks = ctx.mock_slack.send_ephemeral_blocks.call_args_list[1][0][4]
    draft = _draft_text_from_blocks(blocks)
    assert "Offsite — short version" in draft, "revised draft is brief summary"
    assert "*Friday survey*" in draft, "revised draft uses short labels (Slack mrkdwn)"
    confirm_value = _confirm_button_value_from_blocks(blocks)
    _log_ok("second confirm ephemeral")
    return confirm_value


def assert_thread_not_posted_before_user_confirms(ctx: SummarizeReviseE2EContext) -> None:
    ctx.mock_slack.post_thread_message_on_behalf_of_requester.assert_not_called()
    _log_ok("no on-behalf post before confirm")


def assert_user_confirm_posts_revised_summary_on_behalf(
    ctx: SummarizeReviseE2EContext, confirm_value: str,
) -> None:
    simulate_send_thread_reply_button_click(ctx, confirm_value)
    ctx.mock_slack.post_thread_message_on_behalf_of_requester.assert_called_once_with(
        C_TEST, TS_ROOT, to_slack_mrkdwn(REVISED_SUMMARY_DRAFT), U_USER1,
    )
    _log_ok("post_thread_message_on_behalf_of_requester with revised summary")


class TestSummarizeReviseEndToEnd:
    def test_app_mention_summarize_revise_then_post_on_behalf_after_confirm(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        ctx = build_summarize_revise_e2e_context(tmp_path, monkeypatch)
        with patched_summarize_revise_e2e(ctx):
            trigger_app_mention_summarize(ctx)
            first_draft = assert_first_confirm_ui_shows_long_summary(ctx)
            assert_thread_not_posted_before_user_confirms(ctx)
            trigger_revise_after_first_draft(ctx, first_draft)
            assert_revise_rerun_uses_proposed_text(ctx)
            confirm_value = assert_second_confirm_ui_shows_brief_summary(ctx)
            assert_llm_agent_loop_ran_four_times(ctx)
            assert_scripted_llm_turns_fully_consumed(ctx)
            assert_copilot_run_summarized_via_generate_twice(ctx)
            assert_draft_prompt_includes_thread_and_summarize(ctx)
            assert_llm_input_token_budget(
                ctx.fake_backend, log_ok=_log_ok, log_info=_log,
            )
            assert_user_confirm_posts_revised_summary_on_behalf(ctx, confirm_value)
