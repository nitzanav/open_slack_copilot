import time
import threading

from common.llm.llm_client import llm_client
from common.rag import rag
from common.slack.slack_api import slack_api

SUMMARIZE_PROMPT = "Summarize this Slack message in one concise sentence:\n\n{text}"

_last_indexed_ts: dict[str, str] = {}
_scheduler_threads: list[threading.Thread] = []
_scheduler_stop = threading.Event()


def query_channel(channel_id: str, thread_context: str, top_k: int = 10,
                  filters: dict | None = None) -> list[dict]:
    collection = _collection_name(channel_id)
    return rag.query(collection, thread_context, top_k=top_k, filters=filters)


def query_cross_channel(channel_ids: list[str], thread_context: str,
                        exclude_channel: str | None = None, top_k: int = 10) -> list[dict]:
    all_results = []
    for ch_id in channel_ids:
        if ch_id == exclude_channel:
            continue
        results = query_channel(ch_id, thread_context, top_k=top_k)
        all_results.extend(results)

    return _deduplicate_and_rank(all_results, thread_context, top_k)


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


def build_all_missing(channel_ids: list[str], checkpoint_seconds: float = 30 * 86400):
    threads = []
    for ch_id in channel_ids:
        if not is_ready(ch_id):
            t = threading.Thread(target=_safe_build, args=(ch_id, checkpoint_seconds), daemon=True)
            t.start()
            threads.append(t)
    return threads


def schedule_periodic_build(channel_id: str, interval_seconds: float,
                            checkpoint_seconds: float = 30 * 86400):
    def loop():
        while not _scheduler_stop.wait(timeout=interval_seconds):
            _safe_build(channel_id, checkpoint_seconds)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    _scheduler_threads.append(t)
    return t


def stop_scheduler():
    _scheduler_stop.set()
    _scheduler_stop.clear()


def is_ready(channel_id: str) -> bool:
    return rag.collection_exists(_collection_name(channel_id))


def missing_channels(channel_ids: list[str]) -> list[str]:
    return [ch for ch in channel_ids if not is_ready(ch)]


def _safe_build(channel_id: str, checkpoint_seconds: float):
    try:
        build(channel_id, checkpoint_seconds)
    except Exception:
        pass


def reset_state():
    _last_indexed_ts.clear()


def _build_index(channel_id: str, checkpoint_seconds: float):
    oldest = time.time() - checkpoint_seconds
    messages = slack_api.read_channel_history(channel_id, oldest=oldest)
    if not messages:
        rag.ensure_collection(_collection_name(channel_id))
        return

    collection = _collection_name(channel_id)
    is_incremental = channel_id in _last_indexed_ts and rag.collection_exists(collection)
    last_ts = _last_indexed_ts.get(channel_id) if is_incremental else None
    new_messages = _filter_new_messages(messages, last_ts)

    if not new_messages and is_incremental:
        return

    documents = []
    for msg in new_messages:
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

    if not is_incremental:
        rag.delete_collection(collection)

    if documents:
        rag.insert(collection, documents)
    else:
        rag.ensure_collection(collection)

    if messages:
        _last_indexed_ts[channel_id] = max(m.get("ts", "0") for m in messages)


def _filter_new_messages(messages: list[dict], last_ts: str | None) -> list[dict]:
    if not last_ts:
        return messages
    return [m for m in messages if m.get("ts", "0") > last_ts]


def _summarize_message(msg: dict) -> str | None:
    text = msg.get("text", "").strip()
    if not text:
        return None
    try:
        return llm_client.generate(SUMMARIZE_PROMPT.format(text=text))
    except Exception:
        return None


def _deduplicate_and_rank(results: list[dict], query_text: str, top_k: int) -> list[dict]:
    seen = set()
    unique = []
    for r in results:
        key = r.get("ts", "") + r.get("channel", "")
        if key not in seen:
            seen.add(key)
            unique.append(r)

    if len(unique) <= top_k:
        return unique

    query_vec = rag.embed_text(query_text)
    scored = []
    for r in unique:
        doc_vec = rag.embed_text(r.get("text", ""))
        score = sum(a * b for a, b in zip(query_vec, doc_vec))
        scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:top_k]]


def _collection_name(channel_id: str) -> str:
    return f"slack_channel_{channel_id}"
