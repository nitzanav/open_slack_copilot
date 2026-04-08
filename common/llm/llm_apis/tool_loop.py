import json
from typing import Any, Callable

from config.config import settings

from .base import CompletionBackend
from .types import AgentToolLoopResult, NormalizedToolCall, ToolCallRecord

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
):
    for tc in tool_calls:
        try:
            result = run_tool(tc.name, tc.arguments or "{}")
        except Exception as e:
            result = json.dumps({"error": str(e)})
        err_line = _tool_error_line(tc.name, result)
        if err_line:
            tool_errors.append(err_line)
        tool_trace.append(
            ToolCallRecord(
                name=tc.name,
                result_preview=_truncate_preview(result, max_tool_result_preview),
            )
        )
        messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})


def run_agent_tool_loop(
    backend: CompletionBackend,
    system_prompt: str,
    user_prompt: str,
    tools: list[dict[str, Any]],
    run_tool: Callable[[str, str], str],
) -> AgentToolLoopResult:
    max_rounds = int(_LLM.get("max_tool_rounds", 24))
    max_preview = int(_LLM.get("max_tool_result_preview", 600))

    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    if user_prompt:
        messages.append({"role": "user", "content": user_prompt})

    tool_trace: list[ToolCallRecord] = []
    tool_errors: list[str] = []

    for _ in range(max_rounds):
        turn = backend.complete(messages, tools=tools, tool_choice="auto")
        if not turn.tool_calls:
            return AgentToolLoopResult(
                (turn.content or "").strip(), tool_trace, tool_errors
            )
        _append_assistant_tool_calls(messages, turn.content, turn.tool_calls)
        _run_tools_and_append_results(
            messages,
            turn.tool_calls,
            run_tool,
            tool_trace,
            tool_errors,
            max_preview,
        )

    return AgentToolLoopResult("", tool_trace, tool_errors)
