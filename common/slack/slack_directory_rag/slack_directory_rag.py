"""RAG index of Slack workspace directory (users + user groups).

Lets the LLM resolve a person or a user group from free-text ("alice", "backend
team", an email) without paginating users_list/usergroups_list every call.

Built once on startup (if missing) and refreshed on a daily schedule.
"""

import threading

from common.rag import rag
from common.slack.slack_api import slack_api

_COLLECTION = "slack_directory"
_DEFAULT_REFRESH_SECONDS = 24 * 60 * 60

_scheduler_stop = threading.Event()
_scheduler_thread: threading.Thread | None = None
_build_lock = threading.Lock()


def is_ready() -> bool:
    return rag.collection_exists(_COLLECTION)


def build_if_missing() -> None:
    if not is_ready():
        build()


def build() -> None:
    """Rebuild the directory collection from scratch."""
    with _build_lock:
        documents = list(_collect_user_documents()) + list(_collect_usergroup_documents())
        rag.delete_collection(_COLLECTION)
        if documents:
            rag.insert(_COLLECTION, documents)
        else:
            rag.ensure_collection(_COLLECTION)


def search(query: str, kind: str | None = None, top_k: int = 10) -> list[dict]:
    """Semantic search over the directory. ``kind`` is 'user' or 'usergroup'."""
    q = (query or "").strip()
    if not q:
        return []
    filters = {"kind": kind} if kind in ("user", "usergroup") else None
    return rag.query(_COLLECTION, q, top_k=top_k, filters=filters)


def schedule_daily_refresh(interval_seconds: float = _DEFAULT_REFRESH_SECONDS) -> threading.Thread:
    global _scheduler_thread

    def loop():
        while not _scheduler_stop.wait(timeout=interval_seconds):
            try:
                build()
            except Exception:
                pass

    _scheduler_thread = threading.Thread(target=loop, daemon=True)
    _scheduler_thread.start()
    return _scheduler_thread


def stop_scheduler() -> None:
    _scheduler_stop.set()
    _scheduler_stop.clear()


def _collect_user_documents():
    client = slack_api.get_client()
    cursor: str | None = None
    while True:
        kwargs = {"limit": 200}
        if cursor:
            kwargs["cursor"] = cursor
        result = client.users_list(**kwargs)
        for member in result.get("members") or []:
            if not isinstance(member, dict):
                continue
            if member.get("deleted") or member.get("is_bot"):
                continue
            uid = (member.get("id") or "").strip()
            if not uid:
                continue
            profile = member.get("profile") or {}
            display = (profile.get("display_name") or "").strip()
            real = (member.get("real_name") or profile.get("real_name") or "").strip()
            username = (member.get("name") or "").strip()
            email = (profile.get("email") or "").strip()
            title = (profile.get("title") or "").strip()
            text = _user_text(uid, display, real, username, email, title)
            yield {
                "vector": rag.embed_text(text),
                "text": text,
                "kind": "user",
                "id": uid,
                "name": display or real or username,
                "handle": username,
                "email": email,
                "title": title,
            }
        cursor = (result.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break


def _collect_usergroup_documents():
    client = slack_api.get_client()
    cursor: str | None = None
    while True:
        kwargs = {"limit": 200, "include_users": False}
        if cursor:
            kwargs["cursor"] = cursor
        try:
            result = client.usergroups_list(**kwargs)
        except TypeError:
            # Older SDKs / mocks may not accept include_users.
            kwargs.pop("include_users", None)
            result = client.usergroups_list(**kwargs)
        for ug in result.get("usergroups") or []:
            if not isinstance(ug, dict):
                continue
            if ug.get("date_delete"):
                continue
            gid = (ug.get("id") or "").strip()
            if not gid:
                continue
            handle = (ug.get("handle") or "").strip()
            name = (ug.get("name") or "").strip()
            description = (ug.get("description") or "").strip()
            text = _usergroup_text(gid, name, handle, description)
            yield {
                "vector": rag.embed_text(text),
                "text": text,
                "kind": "usergroup",
                "id": gid,
                "name": name,
                "handle": handle,
                "description": description,
            }
        cursor = (result.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break


def _user_text(uid: str, display: str, real: str, username: str, email: str, title: str) -> str:
    parts = [f"user {uid}"]
    if display:
        parts.append(f"display: {display}")
    if real:
        parts.append(f"name: {real}")
    if username:
        parts.append(f"handle: @{username}")
    if email:
        parts.append(f"email: {email}")
    if title:
        parts.append(f"title: {title}")
    return " | ".join(parts)


def _usergroup_text(gid: str, name: str, handle: str, description: str) -> str:
    parts = [f"usergroup {gid}"]
    if name:
        parts.append(f"name: {name}")
    if handle:
        parts.append(f"handle: @{handle}")
    if description:
        parts.append(f"description: {description}")
    return " | ".join(parts)
