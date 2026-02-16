from __future__ import annotations

from adk_claw.context import get_context


def read_memory_file() -> dict:
    """Read the current contents of MEMORY.md.

    Returns the full text so you can review existing sections before merging.
    """
    ctx = get_context()
    if ctx.memory_service is None:
        return {"error": "Memory service not initialized"}

    memory_file = ctx.memory_service._base_dir / "memory" / "MEMORY.md"
    if not memory_file.exists():
        return {"content": "", "note": "MEMORY.md does not exist yet"}

    content = memory_file.read_text(encoding="utf-8")
    return {"content": content}


def write_memory_file(content: str) -> dict:
    """Write the full updated contents to MEMORY.md, replacing the entire file.

    Args:
        content: The complete new content for MEMORY.md.
    """
    ctx = get_context()
    if ctx.memory_service is None:
        return {"error": "Memory service not initialized"}

    memory_file = ctx.memory_service._base_dir / "memory" / "MEMORY.md"
    memory_file.write_text(content, encoding="utf-8")
    ctx.memory_service._dirty = True
    return {"status": "saved"}
