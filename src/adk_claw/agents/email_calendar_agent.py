from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.genai import types

from adk_claw.actions.email_tools import send_email, search_emails, get_email
from adk_claw.actions.calendar_tools import (
    list_events,
    create_event,
    update_event,
    delete_event,
)
from adk_claw.config import Settings
from adk_claw.guardrails.email_guardrails import make_allowlist_callback, make_judge_callback


def create_email_calendar_agent(settings: Settings) -> LlmAgent:
    callbacks: dict = {}

    if settings.email_allowlist:
        allowlist = {
            e.strip().lower()
            for e in settings.email_allowlist.split(",")
            if e.strip()
        }
        callbacks["before_tool_callback"] = make_allowlist_callback(allowlist)

    callbacks["before_agent_callback"] = make_judge_callback(
        settings.email_guardrail_model
    )

    return LlmAgent(
        name="email_calendar_manager",
        description=(
            "Manages email and calendar. "
            "Use this to send emails, search inbox, or manage calendar events."
        ),
        model=Gemini(
            model="gemini-3-flash-preview",
            retry_options=types.HttpRetryOptions(initial_delay=2, attempts=5),
        ),
        instruction=(
            "You manage email and Google Calendar. "
            "Help the user send emails, search their inbox, read emails, "
            "and create/update/delete calendar events. "
            "Complete the request and return the result."
        ),
        tools=[
            send_email,
            search_emails,
            get_email,
            list_events,
            create_event,
            update_event,
            delete_event,
        ],
        **callbacks,
    )
