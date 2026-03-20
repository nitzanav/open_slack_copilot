import pickle
import sqlite3
import threading
import uuid
from pathlib import Path

from fastembed import TextEmbedding

from common.log import log
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue

EMBEDDING_DIM = 384
_client: QdrantClient | None = None
_embedder: TextEmbedding | None = None
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_storage_path() -> str | None:
    try:
        from config.config import settings
        raw = settings.get("rag.storage_path", None)
    except Exception:
        raw = None
    if not raw or raw == ":memory:":
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        storage = _resolve_storage_path()
        if storage:
            _client = QdrantClient(path=storage)
        else:
            _client = QdrantClient(location=":memory:")
    return _client


def set_client(client: QdrantClient):
    global _client
    _client = client


def get_embedder() -> TextEmbedding:
    global _embedder
    if _embedder is None:
        _embedder = TextEmbedding("BAAI/bge-small-en-v1.5")
    return _embedder


def embed_texts(texts: list[str]) -> list[list[float]]:
    return [v.tolist() for v in get_embedder().embed(texts)]


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]


def collection_exists(name: str) -> bool:
    return get_client().collection_exists(name)


def ensure_collection(name: str):
    if not collection_exists(name):
        get_client().create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )


def insert(collection: str, documents: list[dict]):
    ensure_collection(collection)
    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=doc["vector"],
            payload={k: v for k, v in doc.items() if k != "vector"},
        )
        for doc in documents
    ]
    get_client().upsert(collection_name=collection, points=points)


@log
def query(collection: str, query_text: str, top_k: int = 10,
          filters: dict | None = None) -> list[dict]:
    if not collection_exists(collection):
        return []

    vector = embed_text(query_text)
    qdrant_filter = _build_filter(filters) if filters else None
    results = get_client().query_points(
        collection_name=collection,
        query=vector,
        limit=top_k,
        query_filter=qdrant_filter,
    )
    return [r.payload for r in results.points]


def delete_collection(name: str):
    if collection_exists(name):
        get_client().delete_collection(name)


def acquire_lock(key: str) -> threading.Lock:
    with _locks_guard:
        if key not in _locks:
            _locks[key] = threading.Lock()
        return _locks[key]


def list_collections() -> list[str]:
    return [c.name for c in get_client().get_collections().collections]


def count_documents(collection: str) -> int:
    if not collection_exists(collection):
        return 0
    return get_client().count(collection_name=collection).count


def scroll_documents(collection: str, limit: int = 20) -> list[dict]:
    if not collection_exists(collection):
        return []
    result = get_client().scroll(collection_name=collection, limit=limit, with_payload=True, with_vectors=False)
    return [p.payload for p in result[0]]


def is_storage_locked_error(exc: BaseException) -> bool:
    """True when Qdrant local folder is open in another process (portalocker / RuntimeError)."""
    if isinstance(exc, RuntimeError) and "already accessed" in str(exc):
        return True
    return type(exc).__name__ == "AlreadyLocked"


def _storage_root() -> Path | None:
    raw = _resolve_storage_path()
    return Path(raw) if raw else None


def _inspect_all_readonly() -> dict:
    """List collections and point counts without opening Qdrant (SQLite read-only)."""
    root = _storage_root()
    if root is None or not root.is_dir():
        return {}
    coll_root = root / "collection"
    if not coll_root.is_dir():
        return {}
    out: dict[str, int] = {}
    for sub in sorted(coll_root.iterdir()):
        if not sub.is_dir():
            continue
        db = sub / "storage.sqlite"
        if not db.is_file():
            continue
        try:
            con = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
            try:
                n = con.execute("SELECT count(*) FROM points").fetchone()[0]
            finally:
                con.close()
        except Exception:
            n = 0
        out[sub.name] = n
    return out


def inspect_collection_readonly(collection: str, limit: int = 20) -> dict:
    """Sample one collection via SQLite only (works while another process holds Qdrant lock)."""
    root = _storage_root()
    db = (root / "collection" / collection / "storage.sqlite") if root else None
    if not db or not db.is_file():
        return {
            "collection": collection,
            "exists": False,
            "count": 0,
            "documents": [],
        }
    try:
        con = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
        try:
            count = con.execute("SELECT count(*) FROM points").fetchone()[0]
            rows = con.execute(
                "SELECT point FROM points LIMIT ?", (limit,)
            ).fetchall()
        finally:
            con.close()
    except Exception:
        return {
            "collection": collection,
            "exists": False,
            "count": 0,
            "documents": [],
        }
    documents: list[dict] = []
    for (blob,) in rows:
        try:
            pt = pickle.loads(blob)
            pl = getattr(pt, "payload", None)
            if isinstance(pl, dict):
                documents.append(pl)
        except Exception:
            continue
    return {
        "collection": collection,
        "exists": True,
        "count": count,
        "documents": documents,
    }


def inspect_all() -> dict:
    """Return a summary of all collections and their document counts."""
    try:
        client = get_client()
        names = [c.name for c in client.get_collections().collections]
        return {name: client.count(collection_name=name).count for name in names}
    except Exception as e:
        if is_storage_locked_error(e):
            return _inspect_all_readonly()
        raise


def _build_filter(filters: dict) -> Filter:
    conditions = [
        FieldCondition(key=k, match=MatchValue(value=v))
        for k, v in filters.items()
        if v is not None
    ]
    return Filter(must=conditions) if conditions else None
