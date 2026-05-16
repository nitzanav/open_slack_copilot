from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class AgentEvent:
    """Structured notification from the agent loop (tools, turns, etc.) for observers.

    Callers pass ``AgentEventNotifier``; implementations own persistence or live UX
    without coupling the LLM loop to log paths.
    """

    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


AgentEventNotifier = Callable[[AgentEvent], None]


@dataclass(frozen=True)
class NormalizedToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class ChatCompletionTurn:
    """One assistant turn from the provider (text and/or tool calls)."""

    content: str
    tool_calls: tuple[NormalizedToolCall, ...] = ()


@dataclass
class ToolCallRecord:
    name: str
    result_preview: str


@dataclass
class AgentToolLoopResult:
    text: str
    tool_trace: list[ToolCallRecord]
    tool_errors: list[str] = field(default_factory=list)
    waiting_for_confirmation: bool = False
