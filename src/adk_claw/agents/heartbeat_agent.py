from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.genai import types

from adk_claw.actions.heartbeat_tools import (
    add_scheduled_task,
    list_scheduled_tasks,
    remove_scheduled_task,
)


def create_heartbeat_agent() -> LlmAgent:
    return LlmAgent(
        name="heartbeat_manager",
        description=(
            "Manages the agent's own scheduled tasks. "
            "Use this to add, list, or remove recurring tasks."
        ),
        model=Gemini(
            model="gemini-3-flash-preview",
            retry_options=types.HttpRetryOptions(initial_delay=2, attempts=5),
        ),
        instruction=(
            "You manage scheduled heartbeat tasks. "
            "Help the user add, list, or remove tasks. "
            "Supported schedule formats: 'Every N hours', 'Every N minutes', "
            "'Every day at HH:MM'. "
            "Complete the request and return the result."
        ),
        tools=[add_scheduled_task, list_scheduled_tasks, remove_scheduled_task],
    )
