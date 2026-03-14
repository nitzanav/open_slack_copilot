import time

from common.llm.llm_client import llm_client
from common.rag import rag
from common.slack.slack_api import slack_api

SUMMARIZE_PROMPT = "Summarize this Slack message in one concise sentence:\n\n{text}"


def query_channel(channel_id: str, thread_context: str, top_k: int = 10,
                  filters: dict | None = None) -> list[dict]:
    collection = _collection_name(channel_id)
    return rag.query(collection, thread_context, top_k=top_k, filters=filters)


def build(channel_id: str, checkpoint_seconds: float = 30 * 86400):
    lock = rag.acquire_lock(channel_id)
    if not lock.acquire(timeout=0):
        lock.acquire()
        lock.release()
        return

    try:
        _build_index(channel_id, checkpoint_seconds)
    finally:
        lock.release()


def build_if_missing(channel_id: str, checkpoint_seconds: float = 30 * 86400):
    if not rag.collection_exists(_collection_name(channel_id)):
        build(channel_id, checkpoint_seconds)


def is_ready(channel_id: str) -> bool:
    return rag.collection_exists(_collection_name(channel_id))


def _build_index(channel_id: str, checkpoint_seconds: float):
    oldest = time.time() - checkpoint_seconds
    messages = slack_api.read_channel_history(channel_id, oldest=oldest)
    if not messages:
        rag.ensure_collection(_collection_name(channel_id))
        return

    documents = []
    for msg in messages:
        summary = _summarize_message(msg)
        if summary is None:
            continue
        vector = rag.embed_text(summary)
        documents.append({
            "vector": vector,
            "text": summary,
            "original": msg.get("text", ""),
            "from": msg.get("user", ""),
            "ts": msg.get("ts", ""),
            "channel": channel_id,
        })

    collection = _collection_name(channel_id)
    rag.delete_collection(collection)
    if documents:
        rag.insert(collection, documents)
    else:
        rag.ensure_collection(collection)


def _summarize_message(msg: dict) -> str | None:
    text = msg.get("text", "").strip()
    if not text:
        return None
    try:
        return llm_client.generate(SUMMARIZE_PROMPT.format(text=text))
    except Exception:
        return None


def _collection_name(channel_id: str) -> str:
    return f"slack_channel_{channel_id}"
