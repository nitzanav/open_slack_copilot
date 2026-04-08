from typing import Any, Protocol

from .types import ChatCompletionTurn


class CompletionBackend(Protocol):
    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> ChatCompletionTurn:
        """Single chat completion request; returns assistant text and/or tool calls."""
        ...
