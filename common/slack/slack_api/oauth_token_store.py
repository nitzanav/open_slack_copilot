"""Persist Slack user OAuth tokens under the data layer (one JSON file per user)."""

from __future__ import annotations

import os
import ssl
import time
from typing import Any

import certifi
from slack_sdk import WebClient

from common.data_layer import get_collection

_COLLECTION_NAME = "slack_user_oauth"

_owner_user_id_cache: str | None = None


def _col() -> Any:
    return get_collection(_COLLECTION_NAME)


def _resolve_owner_user_id(token: str) -> str | None:
    """Resolve and cache the owner's Slack user_id for the configured user token via auth.test."""
    global _owner_user_id_cache
    if _owner_user_id_cache is not None:
        return _owner_user_id_cache or None
    try:
        client = WebClient(token=token, ssl=ssl.create_default_context(cafile=certifi.where()))
        resp = client.auth_test()
        uid = (resp.get("user_id") or "").strip()
    except Exception:
        uid = ""
    _owner_user_id_cache = uid
    return uid or None


def get_user_token(user_id: str) -> str | None:
    uid = (user_id or "").strip()
    if not uid:
        return None
    row = _col().get(uid)
    t = (row.get("token") or "").strip() if row else ""
    if t:
        return t
    owner_token = (os.environ.get("SLACK_USER_TOKEN") or "").strip()
    if owner_token:
        owner_id = _resolve_owner_user_id(owner_token)
        if owner_id and uid == owner_id:
            return owner_token
    return None


def save_user_token(
    user_id: str,
    token: str,
    *,
    scopes: list[str] | None = None,
) -> None:
    uid = (user_id or "").strip()
    if not uid:
        raise ValueError("user_id is required")
    payload: dict[str, Any] = {
        "token": (token or "").strip(),
        "saved_at": time.time(),
    }
    if scopes is not None:
        payload["scopes"] = list(scopes)
    _col().set(uid, payload)
