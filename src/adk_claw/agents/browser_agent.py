from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.genai import types

from adk_claw.actions.browser_tools import browser_interact, browse_webpage


def create_browser_agent() -> LlmAgent:
    return LlmAgent(
        name="web_browser",
        description=(
            "Browses the web to find information, interact with websites, "
            "or take screenshots. Use this for any web-based tasks."
        ),
        model=Gemini(
            model="gemini-3-flash-preview",
            retry_options=types.HttpRetryOptions(initial_delay=2, attempts=5),
        ),
        instruction=(
            "You are a web browsing specialist. "
            "You can navigate to URLs, click elements, fill forms, and extract text. "
            "Use 'browse_webpage' for simple text extraction or a quick screenshot. "
            "Use 'browser_interact' for multi-step interactions (goto, click, fill, etc.) "
            "where you need to maintain a session. "
            "When using 'browser_interact', you will receive a session_id. "
            "Reuse this session_id for subsequent actions in the same interaction. "
            "After finding the information the user requested or completing the interaction, "
            "summarize your findings and return the result."
        ),
        tools=[browser_interact, browse_webpage],
    )
