from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from google.adk.memory.base_memory_service import BaseMemoryService, SearchMemoryResponse
from google.adk.memory.memory_entry import MemoryEntry
from google.adk.sessions import Session
from google.genai import types

from adk_claw.memory.search import MemorySearchEngine

logger = logging.getLogger(__name__)

_HEADING_RE = re.compile(r"^(#)\s+(.+)$", re.MULTILINE)


def _extract_heading(text: str) -> str | None:
    """Return the text of the first top-level ``# Heading`` in *text*, or None."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
        if stripped and not stripped.startswith("#"):
            # Non-empty, non-heading line before any heading → no heading
            return None
    return None


def _parse_sections(text: str) -> list[tuple[str, str]]:
    """Split *text* into ``(heading, raw_block)`` tuples by top-level ``#`` headings.

    Content before the first heading (if any) gets heading ``""``.
    Each *raw_block* includes the heading line itself so it can be reassembled losslessly.
    """
    if not text.strip():
        return []

    sections: list[tuple[str, str]] = []
    matches = list(_HEADING_RE.finditer(text))

    if not matches:
        return [("", text)]

    # Content before the first heading
    if matches[0].start() > 0:
        preamble = text[: matches[0].start()]
        if preamble.strip():
            sections.append(("", preamble))

    for idx, match in enumerate(matches):
        heading_text = match.group(2).strip()
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        sections.append((heading_text, text[start:end]))

    return sections


def _reassemble(sections: list[tuple[str, str]]) -> str:
    """Join sections back into a single string, ensuring one blank line between them."""
    parts = [block.strip() for _, block in sections]
    return "\n\n".join(parts) + "\n"


class MarkdownMemoryService(BaseMemoryService):
    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._search_engine = MemorySearchEngine()
        self._search_engine.enable_vector_search(base_dir / "memory" / "embeddings.db")
        self._dirty = True
        self._persisted_event_ids: set[str] = set()
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        self._base_dir.mkdir(parents=True, exist_ok=True)
        (self._base_dir / "memory").mkdir(exist_ok=True)

    def _rebuild_index_if_dirty(self) -> None:
        if self._dirty:
            self._search_engine.build_index(self._base_dir)
            self._dirty = False

    async def add_session_to_memory(self, session: Session) -> None:
        """Extract events from session, format as markdown, append to daily log."""
        if not session.events:
            return

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_file = self._base_dir / "memory" / f"{today}.md"

        new_entries: list[str] = []
        for event in session.events:
            event_id = event.id if hasattr(event, "id") else None
            if event_id and event_id in self._persisted_event_ids:
                continue

            author = getattr(event, "author", "unknown")
            text = ""
            if hasattr(event, "content") and event.content:
                parts = getattr(event.content, "parts", [])
                for part in parts:
                    if hasattr(part, "text") and part.text:
                        text += part.text

            if text.strip():
                timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
                new_entries.append(f"**[{timestamp}] {author}**: {text.strip()}")

            if event_id:
                self._persisted_event_ids.add(event_id)

        if new_entries:
            timestamp = datetime.now(timezone.utc).strftime("%H:%M")
            header = ""
            if not log_file.exists():
                header = f"# Session Log — {today}\n\n"

            with open(log_file, "a", encoding="utf-8") as f:
                if header:
                    f.write(header)
                f.write(f"## {timestamp}\n\n")
                f.write("\n".join(new_entries) + "\n\n")

            self._dirty = True
            logger.info("Flushed %d events to %s", len(new_entries), log_file)

    async def search_memory(
        self,
        *,
        app_name: str,
        user_id: str,
        query: str,
    ) -> SearchMemoryResponse:
        """Search markdown memory files using BM25."""
        self._rebuild_index_if_dirty()

        chunks = self._search_engine.search(query, top_k=5)
        memories: list[MemoryEntry] = []
        for chunk in chunks:
            content = types.Content(
                role="user",
                parts=[types.Part(text=f"[{chunk.source_file} — {chunk.heading}]\n{chunk.content}")],
            )
            memories.append(MemoryEntry(content=content))

        return SearchMemoryResponse(memories=memories)

    def upsert_section(self, text: str) -> None:
        """Insert or replace a section in MEMORY.md by matching its heading.

        If the content starts with a top-level ``# Heading``, any existing
        section with the same heading is replaced in-place.  Otherwise the
        content is appended at the end (backwards-compatible).
        """
        memory_file = self._base_dir / "memory" / "MEMORY.md"
        text = text.strip()

        heading = _extract_heading(text)
        if heading is None:
            # No heading — plain append
            with open(memory_file, "a", encoding="utf-8") as f:
                f.write(f"\n{text}\n")
            self._dirty = True
            logger.info("Appended to MEMORY.md (no heading)")
            return

        existing = memory_file.read_text(encoding="utf-8") if memory_file.exists() else ""
        sections = _parse_sections(existing)

        replaced = False
        for i, (sec_heading, _) in enumerate(sections):
            if sec_heading == heading:
                sections[i] = (heading, text)
                replaced = True
                break

        if not replaced:
            sections.append((heading, text))

        memory_file.write_text(_reassemble(sections), encoding="utf-8")
        self._dirty = True
        logger.info(
            "%s section '%s' in MEMORY.md",
            "Replaced" if replaced else "Appended",
            heading,
        )
