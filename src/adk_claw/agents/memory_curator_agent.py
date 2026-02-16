from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.genai import types

from adk_claw.actions.memory_curator_tools import read_memory_file, write_memory_file

CURATOR_INSTRUCTION = """\
You are the Memory Curator. Your job is to maintain MEMORY.md as a concise \
summary of key facts — not a detailed log.

Detailed conversation history is already stored in daily memory files. \
MEMORY.md serves a different purpose: it is a quick-reference overview of \
the user's preferences, recurring topics, important facts, and standing \
instructions. Think of it as a cheat-sheet, not a journal.

When you receive a request to save or update memory:

1. **Read** the current MEMORY.md using `read_memory_file`.
2. **Merge** the new information as a brief summary:
   - Distill the information down to its essence — a sentence or two at most.
   - If a relevant section already exists, update it in place rather than \
adding a duplicate.
   - Deduplicate facts — don't repeat what's already there.
   - Keep each section under a top-level `# Heading`.
3. **Write** the full updated content back using `write_memory_file`.

Guidelines:
- Be extremely concise. One-liners are better than paragraphs.
- Store *what matters* (preferences, names, key decisions), not blow-by-blow details.
- Preserve information the user previously saved — don't drop existing \
sections unless asked to.
- Use consistent heading names so sections can be found and updated later.
"""


def create_memory_curator_agent() -> LlmAgent:
    return LlmAgent(
        name="memory_curator",
        description=(
            "Manages long-term memory (memory/MEMORY.md). "
            "Transfer here to save, update, or reorganize information."
        ),
        model=Gemini(
            model="gemini-3-flash-preview",
            retry_options=types.HttpRetryOptions(initial_delay=1, attempts=5),
        ),
        instruction=CURATOR_INSTRUCTION,
        tools=[read_memory_file, write_memory_file],
    )
