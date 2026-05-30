"""Filesystem KeyValueCollection: ``<root>/<safe_key>.json``."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from common.data_layer.key_value_collection import KeyValueCollection

_BAD = re.compile(r'[/\\:*?"<>|\n\r\x00]')


def _safe_segment(s: str, max_len: int) -> str:
    t = _BAD.sub("_", (s or "").strip())
    if not t:
        return "_"
    if ".." in t:
        t = t.replace("..", "__")
    return t[:max_len] if len(t) <= max_len else t[: max_len - 1] + "…"


def _key_file(root: Path, key: str) -> Path:
    if not (key or "").strip() or ".." in key:
        raise ValueError("Invalid key")
    return root / f"{_safe_segment(key, 200)}.json"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, indent=2, default=str) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(data, encoding="utf-8")
        tmp.replace(path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


class FileKeyValueCollection(KeyValueCollection):
    def __init__(self, collection_root: Path) -> None:
        self._root = collection_root
        self._root.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> dict[str, Any] | None:
        path = _key_file(self._root, key)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def set(self, key: str, value: dict[str, Any]) -> None:
        path = _key_file(self._root, key)
        _atomic_write_json(path, value)

    def delete(self, key: str) -> bool:
        path = _key_file(self._root, key)
        if not path.is_file():
            return False
        try:
            path.unlink()
        except OSError:
            return False
        return True

    def list_keys(self) -> list[str]:
        if not self._root.is_dir():
            return []
        return sorted(
            p.stem for p in self._root.iterdir()
            if p.suffix == ".json" and p.is_file()
        )

    def values(self) -> list[dict[str, Any]]:
        if not self._root.is_dir():
            return []
        out: list[dict[str, Any]] = []
        for p in self._root.iterdir():
            if p.suffix != ".json" or not p.is_file():
                continue
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return out
