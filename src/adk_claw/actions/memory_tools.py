from __future__ import annotations

from adk_claw.context import get_context


async def search_memory(query: str) -> dict:
    """Search long-term memory for relevant past conversations and saved notes.

    Args:
        query: The search query describing what you're looking for.
    """
    ctx = get_context()
    if ctx.memory_service is None:
        return {"error": "Memory service not initialized"}

    results = await ctx.memory_service.search_memory(app_name=None, user_id=None, query=query)
    return {"results": results}