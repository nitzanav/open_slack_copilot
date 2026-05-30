"""Read all ``<name>.json`` watcher configs under ``~/.open_slack_copilot/watchers/``."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from common.watchers.watcher_config import WatcherConfig, validate_watcher_config
from config.config import settings

_logger = logging.getLogger(__name__)


def watchers_root() -> Path:
    return Path(settings.watchers.storage_path).expanduser()


def load_all() -> list[WatcherConfig]:
    """Return every valid watcher config; log + skip invalid files."""
    root = watchers_root()
    if not root.is_dir():
        return []
    out: list[WatcherConfig] = []
    for path in sorted(root.iterdir()):
        if path.suffix != ".json" or not path.is_file():
            continue
        cfg = _try_load_one(path)
        if cfg is not None:
            out.append(cfg)
    return out


def _try_load_one(path: Path) -> WatcherConfig | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _logger.error("watcher %s: %s", path.name, exc)
        return None
    if not isinstance(raw, dict):
        _logger.error("watcher %s: root must be a JSON object", path.name)
        return None
    try:
        return validate_watcher_config(raw, name=path.stem)
    except ValueError as exc:
        _logger.error("watcher %s: %s", path.name, exc)
        return None
