import threading
import time

import pytest
from qdrant_client import QdrantClient

from common.rag import rag


@pytest.fixture(autouse=True)
def fresh_qdrant():
    rag.set_client(QdrantClient(location=":memory:"))
    yield


class TestInsertAndQuery:
    def test_query_returns_top_10(self):
        docs = [
            {"vector": rag.embed_text(f"message about topic {i}"), "text": f"message about topic {i}"}
            for i in range(20)
        ]
        rag.insert("test_col", docs)
        results = rag.query("test_col", "topic 5", top_k=10)
        assert len(results) == 10

    def test_query_with_filter(self):
        docs = [
            {"vector": rag.embed_text("hello from alice"), "text": "hello from alice", "from": "alice"},
            {"vector": rag.embed_text("hello from bob"), "text": "hello from bob", "from": "bob"},
            {"vector": rag.embed_text("another from alice"), "text": "another from alice", "from": "alice"},
        ]
        rag.insert("test_col", docs)
        results = rag.query("test_col", "hello", top_k=10, filters={"from": "alice"})
        assert all(r["from"] == "alice" for r in results)
        assert len(results) == 2

    def test_query_empty_collection(self):
        results = rag.query("nonexistent", "anything")
        assert results == []


class TestCollectionManagement:
    def test_ensure_and_exists(self):
        assert not rag.collection_exists("new_col")
        rag.ensure_collection("new_col")
        assert rag.collection_exists("new_col")

    def test_delete_collection(self):
        rag.ensure_collection("to_delete")
        rag.delete_collection("to_delete")
        assert not rag.collection_exists("to_delete")


class TestConcurrencyLock:
    def test_same_key_serialized(self):
        lock = rag.acquire_lock("ch1")
        acquired = lock.acquire(timeout=0)
        assert acquired

        result = []

        def try_acquire():
            l = rag.acquire_lock("ch1")
            got = l.acquire(timeout=0.1)
            result.append(got)

        t = threading.Thread(target=try_acquire)
        t.start()
        t.join()
        assert result == [False]
        lock.release()

    def test_different_keys_independent(self):
        lock_a = rag.acquire_lock("ch_a")
        lock_b = rag.acquire_lock("ch_b")
        assert lock_a.acquire(timeout=0)
        assert lock_b.acquire(timeout=0)
        lock_a.release()
        lock_b.release()


class TestEmbedding:
    def test_embed_text_returns_correct_dim(self):
        vec = rag.embed_text("test sentence")
        assert len(vec) == rag.EMBEDDING_DIM

    def test_embed_texts_batch(self):
        vecs = rag.embed_texts(["one", "two", "three"])
        assert len(vecs) == 3
        assert all(len(v) == rag.EMBEDDING_DIM for v in vecs)
