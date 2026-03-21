import time
import threading

from common.rag import rag
from common.slack.slack_api import slack_api

_last_indexed_ts: dict[str, str] = {}
_scheduler_threads: list[threading.Thread] = []
_scheduler_stop = threading.Event()

# Index only normal messages (no subtype) plus these subtypes.
_RAG_INDEX_ALLOWED_SUBTYPES = frozenset({"file_share", "bot_message"})


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


def inspect_channel(channel_id: str, limit: int = 20) -> dict:
    """Return info about a channel's RAG: exists, doc count, and sample docs."""
    collection = _collection_name(channel_id)
    try:
        client = rag.get_client()
        exists = client.collection_exists(collection)
        if not exists:
            return {
                "collection": collection,
                "exists": False,
                "count": 0,
                "documents": [],
            }
        cnt = client.count(collection_name=collection).count
        res = client.scroll(
            collection_name=collection,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        docs = [p.payload for p in res[0]]
        return {
            "collection": collection,
            "exists": True,
            "count": cnt,
            "documents": docs,
        }
    except Exception as e:
        if rag.is_storage_locked_error(e):
            return rag.inspect_collection_readonly(collection, limit=limit)
        raise


def inspect_all_channels(limit_per_channel: int = 20) -> dict:
    """Return per-channel RAG detail: counts and sample document payloads."""
    out: dict[str, dict] = {}
    for name in rag.list_collection_names():
        if not name.startswith("slack_channel_"):
            continue
        channel_id = name.removeprefix("slack_channel_")
        out[name] = inspect_channel(channel_id, limit=limit_per_channel)
    return out


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
        if not _slack_message_should_index(msg):
            continue
        raw = (msg.get("text") or "").strip()
        if not raw:
            continue
        text = _index_text_with_reactions(raw, msg)
        vector = rag.embed_text(text)
        user_id = msg.get("user", "") or ""
        documents.append({
            "vector": vector,
            "text": text,
            "from": user_id,
            "from_name": slack_api.get_user_display_name(user_id),
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


def _slack_message_should_index(msg: dict) -> bool:
    subtype = (msg.get("subtype") or "").strip()
    if not subtype:
        return True
    return subtype in _RAG_INDEX_ALLOWED_SUBTYPES


def _index_text_with_reactions(body: str, msg: dict) -> str:
    """Keep reaction signal in the stored / embedded text (Slack adds no subtype for reactions)."""
    reactions = msg.get("reactions")
    if not reactions:
        return body
    parts: list[str] = []
    for r in reactions:
        if not isinstance(r, dict):
            continue
        name = (r.get("name") or "").strip()
        if not name:
            continue
        count = r.get("count")
        if count is None:
            users = r.get("users")
            count = len(users) if isinstance(users, list) else 0
        try:
            n = int(count)
        except (TypeError, ValueError):
            n = 0
        if n > 0:
            parts.append(f":{name}: ×{n}")
    if not parts:
        return body
    parts.sort()
    return f"{body}\n[Reactions: {', '.join(parts)}]"


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


def _ts_display(ts: str) -> str:
    if not ts:
        return "-"
    try:
        return str(int(float(ts)))
    except (ValueError, TypeError):
        part = str(ts).split(".")[0]
        return part if part else "-"


def _message_body(r: dict) -> str:
    return (r.get("text") or "").strip()


def format_rag_context_block(
    channel_id: str,
    thread_ts: str,
    results: list[dict],
    *,
    channel_display_name: str | None = None,
) -> str:
    """Format same-channel RAG hits as plain text for LLM context."""
    if not results:
        return ""
    name = channel_display_name if channel_display_name is not None else (
        slack_api.get_channel_prefixed_name(channel_id)
    )
    user_meta: dict[str, str] = {}
    order: list[str] = []
    for r in results:
        uid = (r.get("from") or "").strip()
        if not uid:
            continue
        if uid not in user_meta:
            order.append(uid)
            label = (r.get("from_name") or "").strip()
            if not label:
                label = slack_api.get_user_display_name(uid)
            user_meta[uid] = label

    lines = [
        f"Channel id: {channel_id}",
        f"Channel name: {name}",
        f"Thread id: {thread_ts}",
        "Users:",
    ]
    for uid in order:
        lines.append(f"  {uid}: {user_meta[uid]}")
    lines.append("")

    for r in results:
        uid = (r.get("from") or "unknown").strip() or "unknown"
        ts = _ts_display(str(r.get("ts") or ""))
        body = _message_body(r)
        lines.append(f"{uid} [{ts}]: {body}")
    return "\n".join(lines)


def format_cross_channel_rag_text(results: list[dict]) -> str:
    """Format cross-channel RAG hits: one text block per source channel."""
    if not results:
        return ""
    by_channel: dict[str, list[dict]] = {}
    for r in results:
        ch = (r.get("channel") or "").strip() or "?"
        by_channel.setdefault(ch, []).append(r)
    blocks = []
    for ch_id in sorted(by_channel.keys()):
        blocks.append(
            format_rag_context_block(ch_id, "—", by_channel[ch_id])
        )
    return "\n\n".join(blocks)
