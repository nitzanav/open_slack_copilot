from typing import Any

from .types import ChatCompletionTurn

_MSG = (
    "Anthropic is not implemented yet. Set llm.provider to openai in config/default.yaml "
    "(or .local.yaml), or finish wiring the Messages API and tools in anthropic.py."
)


class AnthropicCompletion:
    """Placeholder for a future Anthropic Messages API backend."""

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> ChatCompletionTurn:
        raise NotImplementedError(_MSG)
