import tempfile
from pathlib import Path

from adk_claw.memory.service import (
    MarkdownMemoryService,
    _extract_heading,
    _parse_sections,
    _reassemble,
)


class TestExtractHeading:
    def test_simple_heading(self):
        assert _extract_heading("# My Heading\nsome body") == "My Heading"

    def test_no_heading(self):
        assert _extract_heading("just plain text") is None

    def test_text_before_heading(self):
        assert _extract_heading("preamble\n# Heading") is None

    def test_sub_heading_ignored(self):
        assert _extract_heading("## Sub Heading\nbody") is None

    def test_empty(self):
        assert _extract_heading("") is None


class TestParseSections:
    def test_two_sections(self):
        text = "# A\nbody a\n# B\nbody b\n"
        sections = _parse_sections(text)
        assert len(sections) == 2
        assert sections[0][0] == "A"
        assert sections[1][0] == "B"

    def test_preamble_preserved(self):
        text = "some preamble\n# A\nbody\n"
        sections = _parse_sections(text)
        assert sections[0][0] == ""
        assert "preamble" in sections[0][1]
        assert sections[1][0] == "A"

    def test_empty(self):
        assert _parse_sections("") == []

    def test_no_headings(self):
        sections = _parse_sections("just text\n")
        assert len(sections) == 1
        assert sections[0][0] == ""

    def test_roundtrip(self):
        original = "# A\nbody a\n\n# B\nbody b\n"
        sections = _parse_sections(original)
        result = _reassemble(sections)
        assert "# A" in result
        assert "# B" in result
        assert "body a" in result
        assert "body b" in result


class TestUpsertSection:
    def _make_service(self, tmp: Path) -> MarkdownMemoryService:
        (tmp / "memory").mkdir(exist_ok=True)
        return MarkdownMemoryService.__new__(MarkdownMemoryService)

    def _init_service(self, tmp: Path) -> MarkdownMemoryService:
        svc = self._make_service(tmp)
        svc._base_dir = tmp
        svc._dirty = False
        return svc

    def test_replace_existing_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            svc = self._init_service(tmp_path)
            memory_file = tmp_path / "memory" / "MEMORY.md"
            memory_file.write_text("# Recipes\nold content\n\n# Other\nkeep this\n")

            svc.upsert_section("# Recipes\nnew content")

            result = memory_file.read_text()
            assert result.count("# Recipes") == 1
            assert "new content" in result
            assert "old content" not in result
            assert "# Other" in result
            assert "keep this" in result

    def test_append_new_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            svc = self._init_service(tmp_path)
            memory_file = tmp_path / "memory" / "MEMORY.md"
            memory_file.write_text("# Existing\nsome content\n")

            svc.upsert_section("# New Section\nnew stuff")

            result = memory_file.read_text()
            assert "# Existing" in result
            assert "# New Section" in result
            assert "new stuff" in result

    def test_no_heading_appends(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            svc = self._init_service(tmp_path)
            memory_file = tmp_path / "memory" / "MEMORY.md"
            memory_file.write_text("# Existing\ncontent\n")

            svc.upsert_section("just a note without heading")

            result = memory_file.read_text()
            assert "# Existing" in result
            assert "just a note without heading" in result

    def test_upsert_twice_same_heading(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            svc = self._init_service(tmp_path)
            memory_file = tmp_path / "memory" / "MEMORY.md"
            memory_file.write_text("")

            svc.upsert_section("# Heartbeat\nfirst version")
            svc.upsert_section("# Heartbeat\nsecond version")

            result = memory_file.read_text()
            assert result.count("# Heartbeat") == 1
            assert "second version" in result
            assert "first version" not in result

    def test_creates_file_if_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            svc = self._init_service(tmp_path)
            memory_file = tmp_path / "memory" / "MEMORY.md"
            assert not memory_file.exists()

            svc.upsert_section("# Brand New\ncontent here")

            assert memory_file.exists()
            result = memory_file.read_text()
            assert "# Brand New" in result
