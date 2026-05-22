"""Step-aware driver: load conversation from disk, run step tool loops, save."""

from __future__ import annotations

from typing import Callable

from common.conversations import conversations
from common.conversations.conversations import Conversation
from common.llm.llm_client import llm_client
from common.llm.llm_apis.types import (
    AgentEventNotifier,
    AgentToolLoopResult,
    ToolCallRecord,
)
from common.tools.react_context import react_invocation_context


def run_conversation_driver(
    conversation_id: str,
    *,
    tools: list[dict] | None,
    excluded_tools: list[dict] | None,
    tool_dispatch: Callable[[str, str], str] | None,
    on_agent_event: AgentEventNotifier | None = None,
    skip_next_step_intro: bool = False,
) -> tuple[AgentToolLoopResult, Conversation | None]:
    """Run from persisted state until confirmation wait, END, or missing conversation."""
    import common.slack.copilot_pipeline as cp

    last: AgentToolLoopResult | None = None
    while True:
        conversation = conversations.get(conversation_id)
        if not conversation:
            return AgentToolLoopResult("", [], [], False), None
        if conversation.is_end:
            last = last or AgentToolLoopResult(conversation.last_final_text, [], [], False)
            return last, conversation
        if conversation.is_waiting_for_confirmation:
            last = last or AgentToolLoopResult(conversation.last_final_text, [], [], True)
            return last, conversation

        step_name = conversation.current_or_first_step
        inst = conversation.steps.get(step_name, "")
        conversations.set_current_step(conversation_id, step_name)
        if not skip_next_step_intro:
            start_msg = (
                f"Starting step '{step_name}': {inst}" if inst else f"Starting step '{step_name}'."
            )
            conversations.append_message(conversation_id, "system", start_msg)
        skip_next_step_intro = False

        conversation = conversations.get(conversation_id)
        if not conversation:
            return AgentToolLoopResult("", [], [], False), None
        msgs = conversation.messages

        def persist() -> None:
            latest = conversations.get(conversation_id)
            if latest:
                conversations.save(latest)

        effective_tools = cp._resolve_tools(tools, excluded_tools)
        effective_dispatch = tool_dispatch or cp.dispatch_copilot_tool

        loop_out = llm_client.agent_tool_loop_on_messages(
            msgs,
            effective_tools,
            effective_dispatch,
            on_agent_event=on_agent_event,
            stop_on_tool_confirmation=True,
            persist_messages=persist,
        )
        last = loop_out
        conversations.merge_loop_result(
            conversation_id,
            tool_trace=loop_out.tool_trace,
            tool_errors=loop_out.tool_errors,
            final_text=loop_out.text,
        )

        conversation = conversations.get(conversation_id)
        if not conversation:
            return loop_out, None

        if loop_out.waiting_for_confirmation:
            conversations.mark_waiting_for_confirmation(conversation_id, True)
            return loop_out, conversations.get(conversation_id)

        nxt = conversation.next_step_after(step_name)
        if nxt is None:
            conversations.mark_end(conversation_id)
            return loop_out, conversations.get(conversation_id)
        conversations.set_current_step(conversation_id, nxt)


def notify_after_driver_segment(conversation_id: str) -> None:
    """Ephemeral feedback after a resumed segment (mirrors ``react_runner`` rules)."""
    from common.slack.copilot_pipeline import ReactLoopResult
    from common.slack.slack_bot import react_runner

    conversation = conversations.get(conversation_id)
    if not conversation:
        return

    tool_trace: list[ToolCallRecord] = []
    for item in conversation.tool_trace:
        if isinstance(item, dict):
            tool_trace.append(
                ToolCallRecord(
                    name=str(item.get("name") or ""),
                    result_preview=str(item.get("result_preview") or ""),
                ),
            )
        elif isinstance(item, ToolCallRecord):
            tool_trace.append(item)

    loop_out = ReactLoopResult(
        text=conversation.last_final_text,
        tool_trace=tool_trace,
        tool_errors=conversation.tool_errors,
        conversation_id=conversation_id,
        is_waiting_for_confirmation=conversation.is_waiting_for_confirmation,
        is_end=conversation.is_end,
    )
    react_runner._post_loop_ephemeral(
        conversation.channel_id,
        conversation.thread_ts,
        conversation.requester_user_id,
        loop_out,
    )


def continue_with_invocation_context(
    conversation_id: str,
    *,
    tools: list[dict] | None,
    excluded_tools: list[dict] | None,
    tool_dispatch: Callable[[str, str], str] | None,
    on_agent_event: AgentEventNotifier | None,
    skip_next_step_intro: bool,
) -> None:
    conversation = conversations.get(conversation_id)
    if not conversation or conversation.is_end:
        return
    with react_invocation_context(
        conversation.channel_id,
        conversation.thread_ts,
        conversation.prepare_user_id,
        context_kind=conversation.context_kind,
        skill_id=conversation.skill_id,
        action_ts=conversation.action_ts,
        conversation_id=conversation_id,
    ):
        run_conversation_driver(
            conversation_id,
            tools=tools,
            excluded_tools=excluded_tools,
            tool_dispatch=tool_dispatch,
            on_agent_event=on_agent_event,
            skip_next_step_intro=skip_next_step_intro,
        )
    notify_after_driver_segment(conversation_id)
