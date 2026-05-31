"""Abstract key-value store for a named collection of JSON documents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class KeyValueCollection(ABC):
    """One logical collection: JSON-serializable dicts keyed by string ids."""

    @abstractmethod
    def get(self, key: str) -> dict[str, Any] | None:
        pass

    @abstractmethod
    def set(self, key: str, value: dict[str, Any]) -> None:
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Return True if a file existed and was removed."""

    @abstractmethod
    def list_keys(self) -> list[str]:
        """Return keys in this collection (file stems, no extension)."""

    @abstractmethod
    def values(self) -> list[dict[str, Any]]:
        """Return all stored values (rows). Order is unspecified."""
