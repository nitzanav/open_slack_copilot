from pathlib import Path

from dynaconf import Dynaconf, Validator

_CONFIG_DIR = Path(__file__).parent

settings = Dynaconf(
    settings_files=[
        str(_CONFIG_DIR / "default.yaml"),
        str(_CONFIG_DIR / ".local.yaml"),
    ],
    envvar_prefix="SLACK_COPILOT",
    validators=[
        Validator("slack_bot.token", must_exist=True, ne="",
                  messages={"must_exist_true": "SLACK_BOT_TOKEN is required (set via .env, see README)",
                            "operations": "SLACK_BOT_TOKEN must not be empty"}),
        Validator("slack_bot.app_token", must_exist=True, ne="",
                  messages={"must_exist_true": "SLACK_APP_TOKEN is required (set via .env, see README)",
                            "operations": "SLACK_APP_TOKEN must not be empty"}),
        Validator("llm.openai_api_key", must_exist=True, ne="",
                  messages={"must_exist_true": "OPENAI_API_KEY is required (set via .env, see README)",
                            "operations": "OPENAI_API_KEY must not be empty"}),
    ],
)


def parse_duration_seconds(duration: str) -> float:
    unit = duration[-1]
    value = int(duration[:-1])
    multipliers = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return value * multipliers.get(unit, 86400)
