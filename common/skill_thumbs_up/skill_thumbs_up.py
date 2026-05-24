"""Persistent thumbs-up markers per skill: `<skill_dir>/thumbs_up.json`.

Stores `{thread_ts, action_ts}` references to good `skill_runs` rows. Format
on the consumer side renders examples on the fly so we can evolve it without
rewriting history.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from common.progressive_disclosure.progressive_disclosure import SKILLS_ROOT

THUMBS_UP_FILENAME = "thumbs_up.json"
_MAX_KEPT = 200


def _skill_dir(skill_id: str) -> Path | None:
    name = (skill_id or "").strip()
    if not name or "/" in name:
        return None
    return SKILLS_ROOT / name


def _thumbs_up_path(skill_id: str) -> Path | None:
    d = _skill_dir(skill_id)
    if d is None:
        return None
    return d / THUMBS_UP_FILENAME


def _read(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [r for r in data if isinstance(r, dict)]


def _atomic_write(path: Path, refs: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(refs, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def add_reference(skill_id: str, thread_ts: str, action_ts: str) -> bool:
    """Append a `{thread_ts, action_ts}` ref. Dedupe; cap at _MAX_KEPT. Return True on write."""
    path = _thumbs_up_path(skill_id)
    if path is None:
        return False
    if not (skill_id and thread_ts and action_ts):
        return False
    refs = _read(path) if path.is_file() else []
    new_ref = {"thread_ts": thread_ts, "action_ts": action_ts}
    refs = [r for r in refs if not (r.get("thread_ts") == thread_ts and r.get("action_ts") == action_ts)]
    refs.append(new_ref)
    refs = refs[-_MAX_KEPT:]
    _atomic_write(path, refs)
    return True


def recent_references(skill_id: str, limit: int = 20) -> list[dict[str, Any]]:
    path = _thumbs_up_path(skill_id)
    if path is None or not path.is_file():
        return []
    refs = _read(path)
    if limit <= 0:
        return []
    return refs[-limit:]
