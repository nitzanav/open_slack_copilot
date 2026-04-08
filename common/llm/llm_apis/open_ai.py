from typing import Any

from openai import OpenAI

from config.config import settings

from .types import ChatCompletionTurn, NormalizedToolCall


class OpenAICompletion:
    def _client(self) -> OpenAI:
        return OpenAI(api_key=settings.llm.openai_api_key)

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> ChatCompletionTurn:
        model = settings.llm.model
        client = self._client()
        if tools:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
            )
        else:
            response = client.chat.completions.create(model=model, messages=messages)
        msg = response.choices[0].message
        raw_calls = getattr(msg, "tool_calls", None) or ()
        normalized = tuple(
            NormalizedToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments=tc.function.arguments or "{}",
            )
            for tc in raw_calls
        )
        return ChatCompletionTurn(content=msg.content or "", tool_calls=normalized)
