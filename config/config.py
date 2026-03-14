from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).parent / "default.yaml"


def load() -> dict:
    with open(_CONFIG_PATH) as f:
        config = yaml.safe_load(f) or {}
    config.setdefault("llm", {}).setdefault("model", "gpt-4o")
    return config
