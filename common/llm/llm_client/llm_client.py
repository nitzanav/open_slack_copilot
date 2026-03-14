import litellm

from config.config import load as load_config


def generate(system_prompt: str, user_prompt: str = "") -> str:
    model = load_config()["llm"]["model"]
    messages = [{"role": "system", "content": system_prompt}]
    if user_prompt:
        messages.append({"role": "user", "content": user_prompt})
    response = litellm.completion(model=model, messages=messages)
    return response.choices[0].message.content
