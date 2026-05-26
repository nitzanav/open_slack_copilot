"""Shared SQLite-backed Huey instance for cross-process watcher dispatch."""

from __future__ import annotations

from pathlib import Path

from huey import SqliteHuey

_HUEY_DB = Path.home() / ".open_slack_copilot" / "huey.sqlite3"
_HUEY_DB.parent.mkdir(parents=True, exist_ok=True)

huey = SqliteHuey(name="open_slack_copilot", filename=str(_HUEY_DB))
