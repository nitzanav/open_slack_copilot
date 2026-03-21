import json
import re
import ssl
import urllib.request

import certifi
from slack_sdk import WebClient

from common.cache import cache
from common.log import log
from config.config import settings

_client: WebClient | None = None


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())


def get_client() -> WebClient:
    global _client
    if _client is None:
        _client = WebClient(token=settings.slack_bot.token, ssl=_ssl_context())
    return _client


def set_client(client: WebClient):
    global _client
    _client = client


@log
def read_thread(channel_id: str, thread_ts: str) -> list[dict]:
    result = get_client().conversations_replies(channel=channel_id, ts=thread_ts)
    return result["messages"]


def read_channel_history(channel_id: str, oldest: float = 0, limit: int = 1000) -> list[dict]:
    result = get_client().conversations_history(
        channel=channel_id, oldest=str(oldest), limit=limit
    )
    return result["messages"]


@cache
def get_channel_prefixed_name(channel_id: str) -> str:
    if not channel_id:
        return ""
    try:
        result = get_client().conversations_info(channel=channel_id)
        ch = result.get("channel") or {}
        name = (ch.get("name") or "").strip()
        if name:
            return f"#{name}"
        return channel_id
    except Exception:
        return channel_id


@cache
def get_user_display_name(user_id: str) -> str:
    if not user_id:
        return ""
    try:
        result = get_client().users_info(user=user_id)
        user = result.get("user") or {}
        profile = user.get("profile") or {}
        name = (profile.get("display_name") or "").strip()
        if not name:
            name = (user.get("real_name") or "").strip()
        if not name:
            name = (user.get("name") or "").strip()
        return name
    except Exception:
        return ""


@log
def send_ephemeral(channel_id: str, thread_ts: str | None, user_id: str, text: str):
    kwargs: dict = {"channel": channel_id, "user": user_id, "text": text}
    if thread_ts:
        kwargs["thread_ts"] = thread_ts
    get_client().chat_postEphemeral(**kwargs)


@log
def send_ephemeral_blocks(
    channel_id: str,
    thread_ts: str | None,
    user_id: str,
    text: str,
    blocks: list[dict],
):
    kwargs: dict = {
        "channel": channel_id,
        "user": user_id,
        "text": text,
        "blocks": blocks,
    }
    if thread_ts:
        kwargs["thread_ts"] = thread_ts
    get_client().chat_postEphemeral(**kwargs)


@log
def send_dm(user_id: str, text: str):
    client = get_client()
    conv = client.conversations_open(users=user_id)
    ch = conv["channel"]["id"]
    client.chat_postMessage(channel=ch, text=text)


def resolve_user(query: str) -> str | None:
    """Resolve display name, username, or raw user id to a Slack user id."""
    q = (query or "").strip()
    if not q:
        return None
    if re.fullmatch(r"[UW][A-Z0-9]+", q):
        return q
    q_lower = q.lower()
    client = get_client()
    cursor = None
    while True:
        result = client.users_list(cursor=cursor, limit=200)
        for member in result.get("members", []):
            if member.get("deleted") or member.get("is_bot"):
                continue
            uid = member.get("id", "")
            profile = member.get("profile") or {}
            display = (profile.get("display_name") or "").strip().lower()
            real = (member.get("real_name") or "").strip().lower()
            name = (member.get("name") or "").strip().lower()
            if q_lower in (display, real, name) or q_lower == uid.lower():
                return uid
        cursor = result.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return None


@log
def respond_ephemeral(response_url: str, text: str):
    body = json.dumps({"text": text, "response_type": "ephemeral"}).encode()
    req = urllib.request.Request(
        response_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, context=_ssl_context())
