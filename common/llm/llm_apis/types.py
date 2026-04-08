from dataclasses import dataclass, field


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
