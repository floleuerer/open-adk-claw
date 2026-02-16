from __future__ import annotations

import base64
import logging
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> dict:
    """Compose and send an email.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Plain-text email body.
    """
    from adk_claw.context import get_context

    ctx = get_context()
    if ctx.gmail_service is None:
        return {"error": "Gmail service not configured"}

    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    result = ctx.gmail_service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()

    logger.info("Sent email to %s (id=%s)", to, result.get("id"))
    return {"status": "sent", "message_id": result.get("id")}


def search_emails(query: str, max_results: int = 10) -> dict:
    """Search the inbox using Gmail search syntax.

    Args:
        query: Gmail search query, e.g. 'from:alice subject:meeting'.
        max_results: Maximum number of results to return (default 10).
    """
    from adk_claw.context import get_context

    ctx = get_context()
    if ctx.gmail_service is None:
        return {"error": "Gmail service not configured"}

    results = ctx.gmail_service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()

    messages = results.get("messages", [])
    if not messages:
        return {"results": [], "count": 0}

    summaries = []
    for msg_info in messages:
        msg = ctx.gmail_service.users().messages().get(
            userId="me", id=msg_info["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        summaries.append({
            "id": msg_info["id"],
            "from": headers.get("From", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "snippet": msg.get("snippet", ""),
        })

    return {"results": summaries, "count": len(summaries)}


def get_email(email_id: str) -> dict:
    """Read the full content of an email by its ID.

    Args:
        email_id: The Gmail message ID.
    """
    from adk_claw.context import get_context

    ctx = get_context()
    if ctx.gmail_service is None:
        return {"error": "Gmail service not configured"}

    msg = ctx.gmail_service.users().messages().get(
        userId="me", id=email_id, format="full"
    ).execute()

    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}

    # Extract plain-text body
    body = _extract_body(msg.get("payload", {}))

    return {
        "id": msg["id"],
        "thread_id": msg.get("threadId", ""),
        "from": headers.get("From", ""),
        "to": headers.get("To", ""),
        "subject": headers.get("Subject", ""),
        "date": headers.get("Date", ""),
        "body": body,
    }


def _extract_body(payload: dict) -> str:
    """Recursively extract plain-text body from a Gmail message payload."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode(errors="replace")

    for part in payload.get("parts", []):
        text = _extract_body(part)
        if text:
            return text

    return ""
