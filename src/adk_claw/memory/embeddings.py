from __future__ import annotations

import hashlib
import logging
import sqlite3
import struct
from pathlib import Path

import numpy as np
import sqlite_vec

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 768


def _serialize_f32(v: np.ndarray) -> bytes:
    """Serialize a float32 numpy array to raw bytes for sqlite-vec."""
    return struct.pack(f"{len(v)}f", *v)


class EmbeddingStore:
    """SQLite + sqlite-vec store for memory chunk embeddings."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path))
        self._load_vec_extension()
        self._init_tables()

    def _load_vec_extension(self) -> None:
        """Load sqlite-vec extension, handling different SQLite builds."""
        try:
            self._db.enable_load_extension(True)
            sqlite_vec.load(self._db)
            self._db.enable_load_extension(False)
        except AttributeError:
            # Python built without extension support — try loadable path directly
            try:
                loadable = sqlite_vec.loadable_path()
                self._db.load_extension(loadable)
            except AttributeError:
                raise RuntimeError(
                    "sqlite3 was compiled without extension loading support. "
                    "Install Python with a sqlite3 that supports extensions, "
                    "or run inside Docker."
                )

    def _init_tables(self) -> None:
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS chunks(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_file TEXT NOT NULL,
                heading TEXT NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT UNIQUE NOT NULL
            );
        """)
        # sqlite-vec virtual table — create only if it doesn't exist
        try:
            self._db.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(id INTEGER PRIMARY KEY, embedding float[{EMBEDDING_DIM}])"
            )
        except sqlite3.OperationalError:
            pass  # already exists
        self._db.commit()

    def content_hash(self, source_file: str, heading: str, content: str) -> str:
        """SHA-256 hash for deduplication."""
        key = f"{source_file}|{heading}|{content}"
        return hashlib.sha256(key.encode()).hexdigest()

    def get_existing_hashes(self) -> set[str]:
        """Return all content_hash values currently stored."""
        rows = self._db.execute("SELECT content_hash FROM chunks").fetchall()
        return {r[0] for r in rows}

    def upsert_chunks(
        self,
        chunks: list[dict],
        embeddings: list[np.ndarray],
    ) -> int:
        """Insert new chunks with embeddings. Skips existing hashes.

        Each chunk dict: {source_file, heading, content, content_hash}
        Returns count of newly inserted rows.
        """
        inserted = 0
        for chunk, emb in zip(chunks, embeddings):
            try:
                cursor = self._db.execute(
                    "INSERT INTO chunks(source_file, heading, content, content_hash) VALUES(?, ?, ?, ?)",
                    (chunk["source_file"], chunk["heading"], chunk["content"], chunk["content_hash"]),
                )
                row_id = cursor.lastrowid
                self._db.execute(
                    "INSERT INTO vec_chunks(id, embedding) VALUES(?, ?)",
                    (row_id, _serialize_f32(emb)),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                pass  # duplicate content_hash
        self._db.commit()
        return inserted

    def search_similar(self, query_embedding: np.ndarray, top_k: int = 10) -> list[dict]:
        """Return top-k chunks most similar to query_embedding.

        Returns list of {id, source_file, heading, content, distance}.
        """
        rows = self._db.execute(
            """
            SELECT v.id, v.distance, c.source_file, c.heading, c.content
            FROM vec_chunks v
            JOIN chunks c ON c.id = v.id
            WHERE v.embedding MATCH ? AND k = ?
            ORDER BY v.distance
            """,
            (_serialize_f32(query_embedding), top_k),
        ).fetchall()
        return [
            {
                "id": r[0],
                "distance": r[1],
                "source_file": r[2],
                "heading": r[3],
                "content": r[4],
            }
            for r in rows
        ]

    def delete_stale_chunks(self, current_hashes: set[str]) -> int:
        """Remove chunks whose content_hash is not in *current_hashes*.

        Returns the number of deleted rows.
        """
        existing = self.get_existing_hashes()
        stale = existing - current_hashes
        if not stale:
            return 0

        # Find row ids to delete from both tables
        placeholders = ",".join("?" for _ in stale)
        rows = self._db.execute(
            f"SELECT id FROM chunks WHERE content_hash IN ({placeholders})",
            list(stale),
        ).fetchall()
        ids = [r[0] for r in rows]

        if ids:
            id_placeholders = ",".join("?" for _ in ids)
            self._db.execute(
                f"DELETE FROM vec_chunks WHERE id IN ({id_placeholders})", ids
            )
            self._db.execute(
                f"DELETE FROM chunks WHERE id IN ({id_placeholders})", ids
            )
            self._db.commit()

        logger.info("Pruned %d stale embeddings", len(ids))
        return len(ids)

    def get_chunk_by_id(self, chunk_id: int) -> dict | None:
        row = self._db.execute(
            "SELECT id, source_file, heading, content FROM chunks WHERE id = ?",
            (chunk_id,),
        ).fetchone()
        if row is None:
            return None
        return {"id": row[0], "source_file": row[1], "heading": row[2], "content": row[3]}

    def close(self) -> None:
        self._db.close()
