import tempfile
from pathlib import Path

from adk_claw.memory.search import MemorySearchEngine, _split_by_headings


class TestSplitByHeadings:
    def test_single_section(self):
        text = "# Title\nSome content here."
        chunks = _split_by_headings(text, "test.md")
        assert len(chunks) == 1
        assert chunks[0].heading == "Title"
        assert chunks[0].content == "Some content here."
        assert chunks[0].source_file == "test.md"

    def test_multiple_sections(self):
        text = "# First\nContent one.\n# Second\nContent two."
        chunks = _split_by_headings(text, "test.md")
        assert len(chunks) == 2
        assert chunks[0].heading == "First"
        assert chunks[1].heading == "Second"

    def test_no_headings(self):
        text = "Just some text without headings."
        chunks = _split_by_headings(text, "test.md")
        assert len(chunks) == 1
        assert chunks[0].heading == ""
        assert chunks[0].content == "Just some text without headings."

    def test_empty_sections_skipped(self):
        text = "# Empty\n\n# HasContent\nSome text."
        chunks = _split_by_headings(text, "test.md")
        assert len(chunks) == 1
        assert chunks[0].heading == "HasContent"


class TestMemorySearchEngine:
    def _create_workspace(self, tmp: Path):
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

    def test_build_and_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._create_workspace(tmp_path)

            engine = MemorySearchEngine()
            engine.build_index(tmp_path)

            results = engine.search("Python version")
            assert len(results) > 0
            assert any("Python 3.12" in r.content for r in results)

    def test_search_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = MemorySearchEngine()
            engine.build_index(Path(tmp))
            results = engine.search("anything")
            assert results == []

    def test_search_returns_ranked(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._create_workspace(tmp_path)

            engine = MemorySearchEngine()
            engine.build_index(tmp_path)

            results = engine.search("deploy production docker")
            assert len(results) > 0
            # Top result should be about deployment
            assert "deploy" in results[0].content.lower() or "docker" in results[0].content.lower()

    def test_top_k_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._create_workspace(tmp_path)

            engine = MemorySearchEngine()
            engine.build_index(tmp_path)

            results = engine.search("user agent", top_k=2)
            assert len(results) <= 2
