import threading
import uuid

from fastembed import TextEmbedding

from common.log import log
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue

EMBEDDING_DIM = 384
_client: QdrantClient | None = None
_embedder: TextEmbedding | None = None
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def get_client() -> QdrantClient:
    global _client
    if _client is None:
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


def _build_filter(filters: dict) -> Filter:
    conditions = [
        FieldCondition(key=k, match=MatchValue(value=v))
        for k, v in filters.items()
        if v is not None
    ]
    return Filter(must=conditions) if conditions else None
