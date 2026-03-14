from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).parent / "default.yaml"


def load() -> dict:
    with open(_CONFIG_PATH) as f:
        config = yaml.safe_load(f) or {}
    config.setdefault("llm", {}).setdefault("model", "gpt-4o")
    config.setdefault("rag", {}).setdefault("checkpoint_duration", "30d")
    return config


def parse_duration_seconds(duration: str) -> float:
    unit = duration[-1]
    value = int(duration[:-1])
    multipliers = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return value * multipliers.get(unit, 86400)
