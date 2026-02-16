from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)


@dataclass
class MemoryChunk:
    source_file: str
    heading: str
    content: str
    score: float = 0.0


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _split_by_headings(text: str, source_file: str) -> list[MemoryChunk]:
    """Split markdown text into chunks by headings."""
    chunks: list[MemoryChunk] = []
    current_heading = ""
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("#"):
            if current_lines:
                content = "\n".join(current_lines).strip()
                if content:
                    chunks.append(MemoryChunk(
                        source_file=source_file,
                        heading=current_heading,
                        content=content,
                    ))
            current_heading = line.lstrip("#").strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        content = "\n".join(current_lines).strip()
        if content:
            chunks.append(MemoryChunk(
                source_file=source_file,
                heading=current_heading,
                content=content,
            ))

    return chunks


def _rrf_fuse(
    ranked_lists: list[list[MemoryChunk]],
    k: int = 60,
) -> list[MemoryChunk]:
    """Reciprocal Rank Fusion across multiple ranked lists.

    score(doc) = sum(1 / (k + rank_i)) for each list where doc appears.
    """
    # Key by (source_file, heading, content) to merge duplicates
    scores: dict[tuple[str, str, str], float] = {}
    chunk_map: dict[tuple[str, str, str], MemoryChunk] = {}

    for ranked_list in ranked_lists:
        for rank, chunk in enumerate(ranked_list, start=1):
            key = (chunk.source_file, chunk.heading, chunk.content)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            chunk_map[key] = chunk

    fused = []
    for key, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        chunk = chunk_map[key]
        fused.append(MemoryChunk(
            source_file=chunk.source_file,
            heading=chunk.heading,
            content=chunk.content,
            score=score,
        ))

    return fused


@dataclass
class MemorySearchEngine:
    _chunks: list[MemoryChunk] = field(default_factory=list)
    _index: BM25Okapi | None = None
    _embedding_store: object | None = field(default=None, repr=False)
    _vector_enabled: bool = False

    def enable_vector_search(self, db_path: Path) -> None:
        """Enable hybrid search with vector embeddings."""
        try:
            from adk_claw.memory.embeddings import EmbeddingStore
            self._embedding_store = EmbeddingStore(db_path)
            self._vector_enabled = True
            logger.info("Vector search enabled (db: %s)", db_path)
        except Exception:
            logger.exception("Failed to enable vector search, falling back to BM25-only")
            self._vector_enabled = False

    def build_index(self, base_dir: Path) -> None:
        """Scan MEMORY.md + memory/*.md and build BM25 index."""
        self._chunks = []

        memory_file = base_dir / "memory" / "MEMORY.md"
        if memory_file.exists():
            text = memory_file.read_text(encoding="utf-8")
            self._chunks.extend(_split_by_headings(text, "memory/MEMORY.md"))

        memory_dir = base_dir / "memory"
        if memory_dir.is_dir():
            for md_file in sorted(memory_dir.glob("*.md")):
                if md_file.name == "MEMORY.md":
                    continue
                text = md_file.read_text(encoding="utf-8")
                self._chunks.extend(
                    _split_by_headings(text, f"memory/{md_file.name}")
                )

        if self._chunks:
            corpus = [_tokenize(c.content) for c in self._chunks]
            self._index = BM25Okapi(corpus)
        else:
            self._index = None

        if self._vector_enabled:
            self._update_vector_index()

    def _bm25_search(self, query: str, top_k: int = 10) -> list[MemoryChunk]:
        """BM25-only search over indexed chunks."""
        if not self._index or not self._chunks:
            return []

        tokens = _tokenize(query)
        if not tokens:
            return []

        scores = self._index.get_scores(tokens)

        scored = []
        for chunk, score in zip(self._chunks, scores):
            if score > 0:
                scored.append(MemoryChunk(
                    source_file=chunk.source_file,
                    heading=chunk.heading,
                    content=chunk.content,
                    score=float(score),
                ))

        scored.sort(key=lambda c: c.score, reverse=True)
        return scored[:top_k]

    def _vector_search(self, query: str, top_k: int = 10) -> list[MemoryChunk]:
        """Vector similarity search using embeddings."""
        if not self._vector_enabled or self._embedding_store is None:
            return []

        try:
            from adk_claw.memory.embed import embed_query
            query_emb = embed_query(query)
            results = self._embedding_store.search_similar(query_emb, top_k=top_k)
            return [
                MemoryChunk(
                    source_file=r["source_file"],
                    heading=r["heading"],
                    content=r["content"],
                    score=1.0 / (1.0 + r["distance"]),  # convert distance to similarity
                )
                for r in results
            ]
        except Exception:
            logger.exception("Vector search failed, returning empty")
            return []

    def _update_vector_index(self) -> None:
        """Prune stale embeddings, then compute and insert new ones."""
        if not self._vector_enabled or self._embedding_store is None:
            return

        # Build set of current content hashes
        current_hashes: set[str] = set()
        new_chunks = []
        for chunk in self._chunks:
            h = self._embedding_store.content_hash(
                chunk.source_file, chunk.heading, chunk.content
            )
            current_hashes.add(h)

        # Prune vectors that no longer match any source chunk
        self._embedding_store.delete_stale_chunks(current_hashes)

        # Find chunks that still need embedding
        existing_hashes = self._embedding_store.get_existing_hashes()
        for chunk in self._chunks:
            h = self._embedding_store.content_hash(
                chunk.source_file, chunk.heading, chunk.content
            )
            if h not in existing_hashes:
                new_chunks.append({
                    "source_file": chunk.source_file,
                    "heading": chunk.heading,
                    "content": chunk.content,
                    "content_hash": h,
                })

        if not new_chunks:
            logger.info("Vector index up to date (%d chunks)", len(existing_hashes))
            return

        logger.info("Embedding %d new chunks", len(new_chunks))
        try:
            from adk_claw.memory.embed import embed_texts
            texts = [c["content"] for c in new_chunks]
            embeddings = embed_texts(texts)
            inserted = self._embedding_store.upsert_chunks(new_chunks, embeddings)
            logger.info("Inserted %d new embeddings", inserted)
        except Exception:
            logger.exception("Failed to update vector index")

    def search(self, query: str, top_k: int = 5) -> list[MemoryChunk]:
        """Hybrid search: BM25 + vector with RRF fusion.

        Falls back to BM25-only when vector search is disabled.
        """
        bm25_results = self._bm25_search(query, top_k=top_k * 2)

        if not self._vector_enabled:
            return bm25_results[:top_k]

        vector_results = self._vector_search(query, top_k=top_k * 2)

        if not vector_results:
            return bm25_results[:top_k]

        fused = _rrf_fuse([bm25_results, vector_results])
        return fused[:top_k]
