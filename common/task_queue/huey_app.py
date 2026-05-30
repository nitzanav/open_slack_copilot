"""Shared SQLite-backed Huey instance for cross-process background tasks.

Generic task-queue infrastructure: any feature that needs durable, deduped,
cross-process job dispatch can import this ``huey`` instance and decorate a
function with ``@huey.task()``. A single ``huey_consumer`` worker process drains
the SQLite queue.
"""

from __future__ import annotations

from pathlib import Path

from huey import SqliteHuey

from config.config import settings

_HUEY_DB = Path(settings.task_queue.db_path).expanduser()
_HUEY_DB.parent.mkdir(parents=True, exist_ok=True)

huey = SqliteHuey(name="open_slack_copilot", filename=str(_HUEY_DB))
