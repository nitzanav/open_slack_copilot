import os

import litellm

from config.config import settings


def generate(system_prompt: str, user_prompt: str = "") -> str:
    os.environ["OPENAI_API_KEY"] = settings.llm.openai_api_key
    model = settings.llm.model
    messages = [{"role": "system", "content": system_prompt}]
    if user_prompt:
        messages.append({"role": "user", "content": user_prompt})
    response = litellm.completion(model=model, messages=messages)
    return response.choices[0].message.content
