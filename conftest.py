"""Pytest configuration. Set required env vars before config is loaded."""
import os

# Dynaconf requires these at config load. Set before any test imports config.
os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test-token")
os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test-token")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-key")
