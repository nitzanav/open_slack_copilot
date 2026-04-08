from config.config import settings

from .base import CompletionBackend
from .types import (
    AgentToolLoopResult,
    ChatCompletionTurn,
    NormalizedToolCall,
    ToolCallRecord,
)

__all__ = [
    "CompletionBackend",
    "AgentToolLoopResult",
    "ChatCompletionTurn",
    "NormalizedToolCall",
    "ToolCallRecord",
    "get_completion_backend",
]


def get_completion_backend() -> CompletionBackend:
    provider = (settings.llm.get("provider") or "openai").lower().strip()
    if provider in ("openai", "open_ai"):
        from .open_ai import OpenAICompletion

        return OpenAICompletion()
    if provider in ("anthropic", "claude"):
        from .anthropic import AnthropicCompletion

        return AnthropicCompletion()
    raise ValueError(
        f"Unknown llm.provider {provider!r}; expected openai or anthropic."
    )
