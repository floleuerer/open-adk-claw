from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def list_events(days_ahead: int = 7) -> dict:
    """List upcoming calendar events.

    Args:
        days_ahead: Number of days to look ahead (default 7).
    """
    from adk_claw.context import get_context

    ctx = get_context()
    if ctx.calendar_service is None:
        return {"error": "Calendar service not configured"}

    now = datetime.now(timezone.utc)
    time_min = now.isoformat()
    time_max = (now + timedelta(days=days_ahead)).isoformat()

    result = ctx.calendar_service.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime",
        maxResults=50,
    ).execute()

    events = []
    for event in result.get("items", []):
        events.append({
            "id": event["id"],
            "summary": event.get("summary", "(no title)"),
            "start": event["start"].get("dateTime", event["start"].get("date", "")),
            "end": event["end"].get("dateTime", event["end"].get("date", "")),
            "description": event.get("description", ""),
            "attendees": [a.get("email", "") for a in event.get("attendees", [])],
        })

    return {"events": events, "count": len(events)}


def create_event(
    summary: str,
    start: str,
    end: str,
    description: str = "",
    attendees: list[str] = [],
) -> dict:
    """Create a new calendar event.

    Args:
        summary: Event title.
        start: Start time in ISO 8601 format, e.g. '2026-02-14T10:00:00+01:00'.
        end: End time in ISO 8601 format.
        description: Optional event description.
        attendees: Optional list of attendee email addresses.
    """
    from adk_claw.context import get_context

    ctx = get_context()
    if ctx.calendar_service is None:
        return {"error": "Calendar service not configured"}

    event_body: dict = {
        "summary": summary,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
    }
    if description:
        event_body["description"] = description
    if attendees:
        event_body["attendees"] = [{"email": a} for a in attendees]

    event = ctx.calendar_service.events().insert(
        calendarId="primary", body=event_body
    ).execute()

    logger.info("Created event %s: %s", event["id"], summary)
    return {
        "status": "created",
        "event_id": event["id"],
        "summary": summary,
        "link": event.get("htmlLink", ""),
    }


def update_event(
    event_id: str,
    summary: str | None = None,
    start: str | None = None,
    end: str | None = None,
    description: str | None = None,
) -> dict:
    """Update an existing calendar event.

    Args:
        event_id: The Google Calendar event ID.
        summary: New event title (optional).
        start: New start time in ISO 8601 format (optional).
        end: New end time in ISO 8601 format (optional).
        description: New description (optional).
    """
    from adk_claw.context import get_context

    ctx = get_context()
    if ctx.calendar_service is None:
        return {"error": "Calendar service not configured"}

    event = ctx.calendar_service.events().get(
        calendarId="primary", eventId=event_id
    ).execute()

    if summary is not None:
        event["summary"] = summary
    if start is not None:
        event["start"] = {"dateTime": start}
    if end is not None:
        event["end"] = {"dateTime": end}
    if description is not None:
        event["description"] = description

    updated = ctx.calendar_service.events().update(
        calendarId="primary", eventId=event_id, body=event
    ).execute()

    logger.info("Updated event %s", event_id)
    return {
        "status": "updated",
        "event_id": updated["id"],
        "summary": updated.get("summary", ""),
    }


def delete_event(event_id: str) -> dict:
    """Delete a calendar event.

    Args:
        event_id: The Google Calendar event ID.
    """
    from adk_claw.context import get_context

    ctx = get_context()
    if ctx.calendar_service is None:
        return {"error": "Calendar service not configured"}

    ctx.calendar_service.events().delete(
        calendarId="primary", eventId=event_id
    ).execute()

    logger.info("Deleted event %s", event_id)
    return {"status": "deleted", "event_id": event_id}
