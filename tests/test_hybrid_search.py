import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from adk_claw.memory.search import MemoryChunk, MemorySearchEngine, _rrf_fuse


class TestRRFFuse:
    def _chunk(self, name: str) -> MemoryChunk:
        return MemoryChunk(source_file="test.md", heading=name, content=f"content of {name}")

    def test_single_list(self):
        a, b = self._chunk("a"), self._chunk("b")
        fused = _rrf_fuse([[a, b]])
        assert len(fused) == 2
        # First item gets higher score (1/(60+1)) > (1/(60+2))
        assert fused[0].heading == "a"
        assert fused[1].heading == "b"

    def test_two_lists_same_order(self):
        a, b = self._chunk("a"), self._chunk("b")
        fused = _rrf_fuse([[a, b], [a, b]])
        assert fused[0].heading == "a"  # appears rank 1 in both lists

    def test_two_lists_boost_shared(self):
        a, b, c = self._chunk("a"), self._chunk("b"), self._chunk("c")
        # 'b' appears in both lists at rank 1 and rank 2
        fused = _rrf_fuse([[b, a], [c, b]])
        # b gets 1/(60+1) + 1/(60+2) = higher than c's 1/(60+1) or a's 1/(60+2)
        assert fused[0].heading == "b"

    def test_empty_lists(self):
        assert _rrf_fuse([]) == []
        assert _rrf_fuse([[], []]) == []

    def test_scores_assigned(self):
        a = self._chunk("a")
        fused = _rrf_fuse([[a]])
        assert fused[0].score > 0


class TestHybridSearch:
    def _create_workspace(self, tmp: Path):
        """Create a workspace with enough documents for BM25 to work well."""
        memory_dir = tmp / "memory"
        memory_dir.mkdir()

        (memory_dir / "MEMORY.md").write_text(
            "# Important Facts\nThe project uses Python 3.12.\n"
            "# User Preferences\nUser prefers dark mode and vim keybindings.\n"
        )
        (memory_dir / "2025-01-15.md").write_text(
            "# Session Log\n"
            "**[10:00] user**: How do I deploy to production?\n"
            "**[10:01] agent**: Use docker compose up --build.\n"
        )
        (memory_dir / "2025-01-16.md").write_text(
            "# Session Log\n"
            "**[09:00] user**: What's the weather API endpoint?\n"
            "**[09:01] agent**: The weather API is at api.weather.com/v2.\n"
        )

    def test_bm25_only_when_vector_disabled(self):
        """Without vector search, should work like before."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._create_workspace(tmp_path)

            engine = MemorySearchEngine()
            engine.build_index(tmp_path)

            results = engine.search("Python version")
            assert len(results) > 0
            assert any("Python 3.12" in r.content for r in results)

    def test_hybrid_with_mock_embeddings(self):
        """Test hybrid search with mocked embedding calls."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._create_workspace(tmp_path)

            engine = MemorySearchEngine()

            # Mock the embedding store
            mock_store = MagicMock()
            mock_store.get_existing_hashes.return_value = set()
            mock_store.content_hash.side_effect = lambda sf, h, c: f"{sf}|{h}"
            engine._embedding_store = mock_store
            engine._vector_enabled = True

            # Mock embed_texts to avoid API call during build_index
            fake_embeddings = [np.zeros(768, dtype=np.float32) for _ in range(4)]
            with patch("adk_claw.memory.embed.embed_texts", return_value=fake_embeddings):
                engine.build_index(tmp_path)

            # Mock vector search results
            mock_store.search_similar.return_value = [
                {
                    "source_file": "memory/MEMORY.md",
                    "heading": "User Preferences",
                    "content": "User prefers dark mode and vim keybindings.",
                    "distance": 0.1,
                },
            ]

            with patch("adk_claw.memory.embed.embed_query", return_value=np.zeros(768, dtype=np.float32)):
                results = engine.search("dark mode preferences")

            assert len(results) > 0
            # The vector result should appear in fused output
            assert any("dark mode" in r.content for r in results)

    def test_vector_failure_falls_back_to_bm25(self):
        """If vector search returns empty, should still return BM25 results."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._create_workspace(tmp_path)

            engine = MemorySearchEngine()

            # Build index without vector
            engine.build_index(tmp_path)

            # Now enable vector but make it return empty
            engine._vector_enabled = True
            engine._embedding_store = MagicMock()

            with patch.object(engine, "_vector_search", return_value=[]):
                results = engine.search("deploy production docker")

            assert len(results) > 0
            assert any("deploy" in r.content.lower() or "docker" in r.content.lower() for r in results)
