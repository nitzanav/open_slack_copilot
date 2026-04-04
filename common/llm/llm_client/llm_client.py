import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable

import litellm

from common.log import log
from config.config import settings

_LLM_CONFIG = settings.llm
_MAX_TOOL_ROUNDS = _LLM_CONFIG.get("max_tool_rounds", 24)
_MAX_TOOL_RESULT_PREVIEW = _LLM_CONFIG.get("max_tool_result_preview", 600)


@dataclass
class ToolCallRecord:
    name: str
    result_preview: str


@dataclass
class AgentToolLoopResult:
    text: str
    tool_trace: list[ToolCallRecord]
    tool_errors: list[str] = field(default_factory=list)


def _tool_error_line(tool_name: str, result: str) -> str | None:
    """If the tool returned JSON with an 'error' key, return a line for the user-visible draft."""
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


def _truncate_preview(content: str, max_len: int = _MAX_TOOL_RESULT_PREVIEW) -> str:
    s = (content or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


@log
def generate(system_prompt: str, user_prompt: str = "") -> str:
    os.environ["OPENAI_API_KEY"] = settings.llm.openai_api_key
    model = settings.llm.model
    messages = [{"role": "system", "content": system_prompt}]
    if user_prompt:
        messages.append({"role": "user", "content": user_prompt})
    response = litellm.completion(model=model, messages=messages)
    return response.choices[0].message.content


@log
def agent_tool_loop(
    system_prompt: str,
    user_prompt: str,
    tools: list[dict[str, Any]],
    run_tool: Callable[[str, str], str],
) -> AgentToolLoopResult:
    """Run chat completions in a loop, executing tool calls until the model returns text only."""
    os.environ["OPENAI_API_KEY"] = settings.llm.openai_api_key
    model = settings.llm.model
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    if user_prompt:
        messages.append({"role": "user", "content": user_prompt})

    tool_trace: list[ToolCallRecord] = []
    tool_errors: list[str] = []

    for _ in range(_MAX_TOOL_ROUNDS):
        response = litellm.completion(
            model=model, messages=messages, tools=tools, tool_choice="auto"
        )
        msg = response.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        if not tool_calls:
            return AgentToolLoopResult((msg.content or "").strip(), tool_trace, tool_errors)
        _append_assistant_tool_calls(messages, msg, tool_calls)
        _run_tools_and_append_results(
            messages, tool_calls, run_tool, tool_trace, tool_errors
        )

    return AgentToolLoopResult("", tool_trace, tool_errors)


def _append_assistant_tool_calls(
    messages: list[dict[str, Any]], msg: Any, tool_calls: list
):
    messages.append({
        "role": "assistant",
        "content": msg.content or "",
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments or "{}",
                },
            }
            for tc in tool_calls
        ],
    })


def _run_tools_and_append_results(
    messages: list[dict[str, Any]],
    tool_calls: list,
    run_tool: Callable[[str, str], str],
    tool_trace: list[ToolCallRecord],
    tool_errors: list[str],
):
    for tc in tool_calls:
        name = tc.function.name
        try:
            result = run_tool(name, tc.function.arguments or "{}")
        except Exception as e:
            result = json.dumps({"error": str(e)})
        err_line = _tool_error_line(name, result)
        if err_line:
            tool_errors.append(err_line)
        tool_trace.append(
            ToolCallRecord(
                name=name,
                result_preview=_truncate_preview(result),
            )
        )
        messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
