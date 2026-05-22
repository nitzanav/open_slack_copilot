import json
from collections.abc import Callable
from typing import Any

from config.config import settings

from .base import CompletionBackend
from .types import (
    AgentEvent,
    AgentEventNotifier,
    AgentToolLoopResult,
    NormalizedToolCall,
    ToolCallRecord,
)

_LLM = settings.llm


def _tool_error_line(tool_name: str, result: str) -> str | None:
    try:
        obj = json.loads(result)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    err = obj.get("error")
    if not isinstance(err, str) or not err.strip():
        return None
    return f"{tool_name}: {err.strip()}"


def _notify_agent_event(
    notify: AgentEventNotifier | None, event: AgentEvent,
) -> None:
    if notify is None:
        return
    try:
        notify(event)
    except Exception:
        # Observer failures must not break the agent loop.
        pass


def _truncate_preview(content: str, max_len: int) -> str:
    s = (content or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def _append_assistant_tool_calls(
    messages: list[dict[str, Any]],
    content: str,
    tool_calls: tuple[NormalizedToolCall, ...],
):
    messages.append({
        "role": "assistant",
        "content": content or "",
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": tc.arguments or "{}"},
            }
            for tc in tool_calls
        ],
    })


def _run_tools_and_append_results(
    messages: list[dict[str, Any]],
    tool_calls: tuple[NormalizedToolCall, ...],
    run_tool: Callable[[str, str], str],
    tool_trace: list[ToolCallRecord],
    tool_errors: list[str],
    max_tool_result_preview: int,
    notify: AgentEventNotifier | None,
):
    for tc in tool_calls:
        try:
            result = run_tool(tc.name, tc.arguments or "{}")
        except Exception as e:
            result = json.dumps({"error": str(e)})
        err_line = _tool_error_line(tc.name, result)
        if err_line:
            tool_errors.append(err_line)
        record = ToolCallRecord(
            name=tc.name,
            result_preview=_truncate_preview(result, max_tool_result_preview),
        )
        tool_trace.append(record)
        _notify_agent_event(
            notify,
            AgentEvent(
                "tool_result",
                {
                    "tool_call_id": tc.id,
                    "name": record.name,
                    "result_preview": record.result_preview,
                },
            ),
        )
        messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})


def run_agent_tool_loop(
    backend: CompletionBackend,
    system_prompt: str,
    user_prompt: str,
    tools: list[dict[str, Any]],
    run_tool: Callable[[str, str], str],
    *,
    on_agent_event: AgentEventNotifier | None = None,
) -> AgentToolLoopResult:
    max_rounds = int(_LLM.get("max_tool_rounds", 24))
    max_preview = int(_LLM.get("max_tool_result_preview", 600))

    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    if user_prompt:
        messages.append({"role": "user", "content": user_prompt})

    tool_trace: list[ToolCallRecord] = []
    tool_errors: list[str] = []

    for round_idx in range(max_rounds):
        turn = backend.complete(messages, tools=tools, tool_choice="auto")
        if not turn.tool_calls:
            text = (turn.content or "").strip()
            _notify_agent_event(
                on_agent_event,
                AgentEvent(
                    "loop_complete",
                    {"text": text, "round_index": round_idx},
                ),
            )
            return AgentToolLoopResult(text, tool_trace, tool_errors)
        _append_assistant_tool_calls(messages, turn.content, turn.tool_calls)
        _notify_agent_event(
            on_agent_event,
            AgentEvent(
                "assistant_tool_calls",
                {
                    "round_index": round_idx,
                    "content": turn.content or "",
                    "tools": [
                        {"id": tc.id, "name": tc.name, "arguments": tc.arguments or "{}"}
                        for tc in turn.tool_calls
                    ],
                },
            ),
        )
        _run_tools_and_append_results(
            messages,
            turn.tool_calls,
            run_tool,
            tool_trace,
            tool_errors,
            max_preview,
            on_agent_event,
        )

    _notify_agent_event(
        on_agent_event,
        AgentEvent(
            "loop_max_rounds",
            {"max_rounds": max_rounds},
        ),
    )
    return AgentToolLoopResult("", tool_trace, tool_errors, False)


def _last_tool_batch_requests_confirmation(
    messages: list[dict[str, Any]],
    n_tools: int,
) -> bool:
    if n_tools <= 0:
        return False
    tail = messages[-n_tools:]
    for msg in tail:
        if msg.get("role") != "tool":
            continue
        content = msg.get("content") or ""
        try:
            obj = json.loads(content)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("status") == "tool_confirmation_requested":
            return True
    return False


def run_agent_tool_loop_on_messages(
    backend: CompletionBackend,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    run_tool: Callable[[str, str], str],
    *,
    on_agent_event: AgentEventNotifier | None = None,
    stop_on_tool_confirmation: bool = False,
    persist_messages: Callable[[], None] | None = None,
) -> AgentToolLoopResult:
    """Like ``run_agent_tool_loop`` but uses existing ``messages`` (mutated in place).

    When ``stop_on_tool_confirmation`` is True, stops after a tool result whose JSON
    contains ``{"status": "tool_confirmation_requested"}`` instead of continuing the loop.
    """
    max_rounds = int(_LLM.get("max_tool_rounds", 24))
    max_preview = int(_LLM.get("max_tool_result_preview", 600))

    tool_trace: list[ToolCallRecord] = []
    tool_errors: list[str] = []

    for round_idx in range(max_rounds):
        turn = backend.complete(messages, tools=tools, tool_choice="auto")
        if not turn.tool_calls:
            text = (turn.content or "").strip()
            _notify_agent_event(
                on_agent_event,
                AgentEvent(
                    "loop_complete",
                    {"text": text, "round_index": round_idx},
                ),
            )
            if persist_messages:
                persist_messages()
            return AgentToolLoopResult(text, tool_trace, tool_errors, False)
        _append_assistant_tool_calls(messages, turn.content, turn.tool_calls)
        if persist_messages:
            persist_messages()
        _notify_agent_event(
            on_agent_event,
            AgentEvent(
                "assistant_tool_calls",
                {
                    "round_index": round_idx,
                    "content": turn.content or "",
                    "tools": [
                        {"id": tc.id, "name": tc.name, "arguments": tc.arguments or "{}"}
                        for tc in turn.tool_calls
                    ],
                },
            ),
        )
        n_tc = len(turn.tool_calls)
        _run_tools_and_append_results(
            messages,
            turn.tool_calls,
            run_tool,
            tool_trace,
            tool_errors,
            max_preview,
            on_agent_event,
        )
        if persist_messages:
            persist_messages()
        if stop_on_tool_confirmation and _last_tool_batch_requests_confirmation(
            messages, n_tc,
        ):
            text = (turn.content or "").strip()
            _notify_agent_event(
                on_agent_event,
                AgentEvent(
                    "loop_complete",
                    {"text": text, "round_index": round_idx, "stopped_for_confirmation": True},
                ),
            )
            if persist_messages:
                persist_messages()
            return AgentToolLoopResult(text, tool_trace, tool_errors, True)

    _notify_agent_event(
        on_agent_event,
        AgentEvent(
            "loop_max_rounds",
            {"max_rounds": max_rounds},
        ),
    )
    return AgentToolLoopResult("", tool_trace, tool_errors, False)
