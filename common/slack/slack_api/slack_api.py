import json
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
def send_ephemeral(channel_id: str, thread_ts: str, user_id: str, text: str):
    get_client().chat_postEphemeral(
        channel=channel_id, thread_ts=thread_ts, user=user_id, text=text
    )


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
