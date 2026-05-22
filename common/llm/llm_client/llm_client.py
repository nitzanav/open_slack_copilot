from typing import Any, Callable

from common.log import log
from common.llm.llm_apis import get_completion_backend
from common.llm.llm_apis.tool_loop import run_agent_tool_loop, run_agent_tool_loop_on_messages
from common.llm.llm_apis.types import (
    AgentEvent,
    AgentEventNotifier,
    AgentToolLoopResult,
    ToolCallRecord,
)

__all__ = [
    "AgentEvent",
    "AgentEventNotifier",
    "AgentToolLoopResult",
    "ToolCallRecord",
    "generate",
    "agent_tool_loop",
    "agent_tool_loop_on_messages",
]


@log
def generate(system_prompt: str, user_prompt: str = "") -> str:
    messages = [{"role": "system", "content": system_prompt}]
    if user_prompt:
        messages.append({"role": "user", "content": user_prompt})
    turn = get_completion_backend().complete(messages)
    return turn.content or ""


@log
def agent_tool_loop(
    system_prompt: str,
    user_prompt: str,
    tools: list[dict[str, Any]],
    run_tool: Callable[[str, str], str],
    *,
    on_agent_event: AgentEventNotifier | None = None,
) -> AgentToolLoopResult:
    return run_agent_tool_loop(
        get_completion_backend(),
        system_prompt,
        user_prompt,
        tools,
        run_tool,
        on_agent_event=on_agent_event,
    )


@log
def agent_tool_loop_on_messages(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    run_tool: Callable[[str, str], str],
    *,
    on_agent_event: AgentEventNotifier | None = None,
    stop_on_tool_confirmation: bool = False,
    persist_messages: Callable[[], None] | None = None,
) -> AgentToolLoopResult:
    return run_agent_tool_loop_on_messages(
        get_completion_backend(),
        messages,
        tools,
        run_tool,
        on_agent_event=on_agent_event,
        stop_on_tool_confirmation=stop_on_tool_confirmation,
        persist_messages=persist_messages,
    )
