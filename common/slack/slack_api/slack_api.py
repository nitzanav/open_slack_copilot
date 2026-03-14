from slack_sdk import WebClient

from config.config import settings

_client: WebClient | None = None


def get_client() -> WebClient:
    global _client
    if _client is None:
        _client = WebClient(token=settings.slack_bot.token)
    return _client


def set_client(client: WebClient):
    global _client
    _client = client


def read_thread(channel_id: str, thread_ts: str) -> list[dict]:
    result = get_client().conversations_replies(channel=channel_id, ts=thread_ts)
    return result["messages"]


def read_channel_history(channel_id: str, oldest: float = 0, limit: int = 1000) -> list[dict]:
    result = get_client().conversations_history(
        channel=channel_id, oldest=str(oldest), limit=limit
    )
    return result["messages"]


def send_ephemeral(channel_id: str, thread_ts: str, user_id: str, text: str):
    get_client().chat_postEphemeral(
        channel=channel_id, thread_ts=thread_ts, user=user_id, text=text
    )
