from __future__ import annotations

import asyncio
import base64
import logging
from email.mime.text import MIMEText

from googleapiclient.discovery import Resource

from adk_claw.channels.base import BaseChannel
from adk_claw.queue import MessageQueue

logger = logging.getLogger(__name__)


class GmailChannel(BaseChannel):
    def __init__(
        self,
        service: Resource,
        queue: MessageQueue,
        poll_interval: float = 30.0,
        label_filter: str = "",
    ) -> None:
        self._service = service
        self._queue = queue
        self._poll_interval = poll_interval
        self._label_filter = label_filter
        self._seen_ids: set[str] = set()
        self._poll_task: asyncio.Task | None = None
        self._running = False
        # Map sender email -> threadId for reply threading
        self._threads: dict[str, str] = {}

    async def start(self) -> None:
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(
            "Gmail polling started (interval=%ss, label_filter=%r)",
            self._poll_interval,
            self._label_filter,
        )

    async def stop(self) -> None:
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("Gmail polling stopped")

    async def send_reply(self, chat_id: str, text: str) -> None:
        if not text.strip():
            return

        message = MIMEText(text)
        message["to"] = chat_id
        message["subject"] = "Re:"

        body: dict = {"raw": base64.urlsafe_b64encode(message.as_bytes()).decode()}

        # Thread the reply if we have a thread ID for this sender
        thread_id = self._threads.get(chat_id)
        if thread_id:
            body["threadId"] = thread_id

        await asyncio.to_thread(
            self._service.users().messages().send(userId="me", body=body).execute
        )
        logger.info("Sent Gmail reply to %s", chat_id)

    async def _poll_loop(self) -> None:
        # Seed seen IDs on first poll to avoid processing old emails
        await self._seed_seen_ids()

        while self._running:
            try:
                await self._check_new_emails()
            except Exception:
                logger.exception("Error polling Gmail")
            await asyncio.sleep(self._poll_interval)

    async def _seed_seen_ids(self) -> None:
        """Load existing unread message IDs so we don't process old emails on startup."""
        try:
            query = "is:unread"
            if self._label_filter:
                query += f" label:{self._label_filter}"

            result = await asyncio.to_thread(
                self._service.users().messages().list(
                    userId="me", q=query, maxResults=100
                ).execute
            )
            for msg in result.get("messages", []):
                self._seen_ids.add(msg["id"])
            logger.info("Seeded %d existing unread message IDs", len(self._seen_ids))
        except Exception:
            logger.exception("Error seeding seen IDs")

    async def _check_new_emails(self) -> None:
        query = "is:unread"
        if self._label_filter:
            query += f" label:{self._label_filter}"

        result = await asyncio.to_thread(
            self._service.users().messages().list(
                userId="me", q=query, maxResults=20
            ).execute
        )

        messages = result.get("messages", [])
        if not messages:
            return

        for msg_info in messages:
            msg_id = msg_info["id"]
            if msg_id in self._seen_ids:
                continue

            self._seen_ids.add(msg_id)

            msg = await asyncio.to_thread(
                self._service.users().messages().get(
                    userId="me", id=msg_id, format="full"
                ).execute
            )

            sender, subject, body = self._parse_email(msg)
            if not sender:
                continue

            # Store thread ID for reply threading
            thread_id = msg.get("threadId")
            if thread_id:
                self._threads[sender] = thread_id

            text = f"[Email] From: {sender}\nSubject: {subject}\n\n{body}"
            logger.info("New email from %s: %s", sender, subject[:50])

            await self._queue.push(sender, text, sender)

            # Mark as read
            await asyncio.to_thread(
                self._service.users().messages().modify(
                    userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}
                ).execute
            )

    def _parse_email(self, msg: dict) -> tuple[str, str, str]:
        """Extract sender, subject, and plain-text body from a Gmail message."""
        headers = {
            h["name"]: h["value"]
            for h in msg.get("payload", {}).get("headers", [])
        }
        sender = headers.get("From", "")
        subject = headers.get("Subject", "")

        # Extract email address from "Name <email>" format
        if "<" in sender and ">" in sender:
            sender = sender[sender.index("<") + 1 : sender.index(">")]

        body = self._extract_body(msg.get("payload", {}))
        return sender, subject, body

    def _extract_body(self, payload: dict) -> str:
        """Recursively extract plain-text body from a Gmail message payload."""
        if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode(errors="replace")

        for part in payload.get("parts", []):
            text = self._extract_body(part)
            if text:
                return text

        return ""
