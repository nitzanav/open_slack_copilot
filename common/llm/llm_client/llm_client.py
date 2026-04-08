from typing import Any, Callable

from common.log import log
from common.llm.llm_apis import get_completion_backend
from common.llm.llm_apis.tool_loop import run_agent_tool_loop
from common.llm.llm_apis.types import AgentToolLoopResult, ToolCallRecord

__all__ = [
    "AgentToolLoopResult",
    "ToolCallRecord",
    "generate",
    "agent_tool_loop",
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
) -> AgentToolLoopResult:
    return run_agent_tool_loop(
        get_completion_backend(),
        system_prompt,
        user_prompt,
        tools,
        run_tool,
    )
