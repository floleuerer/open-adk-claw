import tempfile
from pathlib import Path

import numpy as np
import pytest

from adk_claw.memory.embeddings import EMBEDDING_DIM, EmbeddingStore


def _can_load_sqlite_vec() -> bool:
    try:
        import tempfile as tf
        with tf.TemporaryDirectory() as d:
            EmbeddingStore(Path(d) / "test.db").close()
        return True
    except (RuntimeError, Exception):
        return False


skip_no_sqlite_vec = pytest.mark.skipif(
    not _can_load_sqlite_vec(),
    reason="sqlite-vec extension not available (requires Python built with extension support)",
)


@skip_no_sqlite_vec
class TestEmbeddingStore:
    def setup_method(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._db_path = Path(self._tmp.name) / "test.db"
        self._store = EmbeddingStore(self._db_path)

    def teardown_method(self):
        self._store.close()
        self._tmp.cleanup()

    def _random_embedding(self) -> np.ndarray:
        return np.random.randn(EMBEDDING_DIM).astype(np.float32)

    def test_content_hash_deterministic(self):
        h1 = self._store.content_hash("file.md", "heading", "content")
        h2 = self._store.content_hash("file.md", "heading", "content")
        assert h1 == h2

    def test_content_hash_varies(self):
        h1 = self._store.content_hash("a.md", "h", "c")
        h2 = self._store.content_hash("b.md", "h", "c")
        assert h1 != h2

    def test_upsert_and_search(self):
        chunks = [
            {
                "source_file": "test.md",
                "heading": "Section A",
                "content": "Python is great",
                "content_hash": self._store.content_hash("test.md", "Section A", "Python is great"),
            },
            {
                "source_file": "test.md",
                "heading": "Section B",
                "content": "JavaScript is dynamic",
                "content_hash": self._store.content_hash("test.md", "Section B", "JavaScript is dynamic"),
            },
        ]
        embeddings = [self._random_embedding(), self._random_embedding()]

        inserted = self._store.upsert_chunks(chunks, embeddings)
        assert inserted == 2

        # Search with the first embedding should return results
        results = self._store.search_similar(embeddings[0], top_k=2)
        assert len(results) == 2
        # The closest result to embeddings[0] should be Section A
        assert results[0]["content"] == "Python is great"

    def test_upsert_deduplication(self):
        chunk = {
            "source_file": "test.md",
            "heading": "A",
            "content": "hello",
            "content_hash": self._store.content_hash("test.md", "A", "hello"),
        }
        emb = self._random_embedding()

        assert self._store.upsert_chunks([chunk], [emb]) == 1
        assert self._store.upsert_chunks([chunk], [emb]) == 0  # duplicate

    def test_get_existing_hashes(self):
        assert self._store.get_existing_hashes() == set()

        chunk = {
            "source_file": "f.md",
            "heading": "H",
            "content": "C",
            "content_hash": "abc123",
        }
        self._store.upsert_chunks([chunk], [self._random_embedding()])
        assert "abc123" in self._store.get_existing_hashes()

    def test_get_chunk_by_id(self):
        chunk = {
            "source_file": "f.md",
            "heading": "H",
            "content": "test content",
            "content_hash": self._store.content_hash("f.md", "H", "test content"),
        }
        self._store.upsert_chunks([chunk], [self._random_embedding()])

        result = self._store.get_chunk_by_id(1)
        assert result is not None
        assert result["content"] == "test content"

        assert self._store.get_chunk_by_id(999) is None

    def test_search_empty_store(self):
        results = self._store.search_similar(self._random_embedding(), top_k=5)
        assert results == []
