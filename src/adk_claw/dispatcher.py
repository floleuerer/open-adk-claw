from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Callable, Awaitable

from google.adk.runners import Runner
from google.adk.agents.run_config import RunConfig
from google.genai import types

from adk_claw.config import Settings
from adk_claw.memory.service import MarkdownMemoryService
from adk_claw.queue import QueuedMessage

logger = logging.getLogger(__name__)

SendReply = Callable[[str, str], Awaitable[None]]

_CURATION_PROMPT = (
    "Summarize the key facts, preferences, and decisions from this conversation "
    "and save them to long-term memory."
)

_REAPER_INTERVAL = 60.0  # seconds between reaper scans


@dataclass
class WorkItem:
    chat_id: str
    messages: list[QueuedMessage]
    lane: str


class Dispatcher:
    """Lane-based orchestrator for concurrent message & heartbeat processing.

    Owns two asyncio.Queue lanes (chat and heartbeat), each consumed by an
    independent worker coroutine.  Chat messages and heartbeat tasks process
    concurrently across lanes but sequentially within each lane.

    Idle sessions are automatically rotated after ``session_idle_timeout``
    seconds of inactivity: the memory curator runs, the session is flushed
    to the daily log, and a fresh session is created.
    """

    def __init__(
        self,
        runner: Runner,
        settings: Settings,
        memory_service: MarkdownMemoryService,
        send_reply: SendReply,
        curator_runner: Runner | None = None,
    ) -> None:
        self._runner = runner
        self._settings = settings
        self._memory_service = memory_service
        self._send_reply = send_reply
        self._curator_runner = curator_runner
        self._chat_queue: asyncio.Queue[WorkItem] = asyncio.Queue()
        self._heartbeat_queue: asyncio.Queue[WorkItem] = asyncio.Queue()
        self._sessions: dict[str, str] = {}
        self._last_activity: dict[str, float] = {}
        self._chat_locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, chat_id: str) -> asyncio.Lock:
        if chat_id not in self._chat_locks:
            self._chat_locks[chat_id] = asyncio.Lock()
        return self._chat_locks[chat_id]

    async def enqueue_chat(self, chat_id: str, messages: list[QueuedMessage]) -> None:
        """Called by MessageQueue when a debounced batch is ready."""
        await self._chat_queue.put(WorkItem(chat_id=chat_id, messages=messages, lane="chat"))

    async def enqueue_heartbeat(self, schedule: str, prompt: str) -> None:
        """Called by HeartbeatScheduler when a heartbeat fires."""
        if not self._settings.admin_chat_id:
            logger.warning("No admin_chat_id set, skipping heartbeat")
            return
        chat_id = self._settings.admin_chat_id
        messages = [QueuedMessage(
            chat_id=chat_id,
            text=f"[Heartbeat — {schedule}]\n{prompt}",
            user_name="system",
        )]
        await self._heartbeat_queue.put(WorkItem(chat_id=chat_id, messages=messages, lane="heartbeat"))

    async def run(self) -> None:
        """Start lane workers and the session reaper concurrently."""
        await asyncio.gather(
            self._worker(self._chat_queue, "chat"),
            self._worker(self._heartbeat_queue, "heartbeat"),
            self._session_reaper(),
        )

    async def _worker(self, queue: asyncio.Queue[WorkItem], lane_name: str) -> None:
        """Pull work items and process sequentially within this lane."""
        while True:
            item = await queue.get()
            try:
                await self._process(item)
            except Exception:
                logger.exception("Error processing %s item for chat %s", lane_name, item.chat_id)
            finally:
                queue.task_done()

    async def _process(self, item: WorkItem) -> None:
        """Run the agent for a work item and send the reply."""
        chat_id = item.chat_id
        messages = item.messages
        lock = self._get_lock(chat_id)

        async with lock:
            logger.info("=== [RECEIVE] Chat: %s | Messages: %d | Lane: %s ===", chat_id, len(messages), item.lane)
            # Update activity timestamp
            self._last_activity[chat_id] = time.monotonic()

            # Combine messages into a single prompt
            if len(messages) == 1:
                combined = messages[0].text
            else:
                parts = []
                for msg in messages:
                    parts.append(f"{msg.user_name}: {msg.text}")
                combined = "\n".join(parts)

            # Get or create session
            if chat_id not in self._sessions:
                session = await self._runner.session_service.create_session(
                    app_name=self._settings.app_name,
                    user_id=chat_id,
                )
                self._sessions[chat_id] = session.id

            session_id = self._sessions[chat_id]

            # Build content
            content = types.Content(
                role="user",
                parts=[types.Part(text=combined)],
            )

            # Run agent
            response_parts: list[str] = []
            try:
                async for event in self._runner.run_async(
                    user_id=chat_id,
                    session_id=session_id,
                    new_message=content,
                    run_config=RunConfig(max_llm_calls=500),
                ):
                    if hasattr(event, "content") and event.content:
                        ev_parts = getattr(event.content, "parts", [])
                        for part in ev_parts:
                            if hasattr(part, "text") and part.text:
                                response_parts.append(part.text)
            except Exception:
                logger.exception("Error running agent for chat %s", chat_id)
                response_parts.append("Sorry, I encountered an error processing your message.")

            # Send reply
            response_text = "\n".join(response_parts).strip()
            if response_text:
                await self._send_reply(chat_id, response_text)

    async def _session_reaper(self) -> None:
        """Periodically scan for idle sessions and rotate them."""
        while True:
            await asyncio.sleep(_REAPER_INTERVAL)
            timeout = self._settings.session_idle_timeout
            now = time.monotonic()

            idle_chats = [
                chat_id
                for chat_id, last in self._last_activity.items()
                if (now - last) >= timeout and chat_id in self._sessions
            ]

            for chat_id in idle_chats:
                try:
                    await self._rotate_session(chat_id)
                except Exception:
                    logger.exception("Error rotating session for chat %s", chat_id)

    async def _rotate_session(self, chat_id: str) -> None:
        """Curate memory, flush session to daily log, and create a fresh session."""
        lock = self._get_lock(chat_id)

        async with lock:
            # Re-check: user may have become active while we waited for the lock
            now = time.monotonic()
            last = self._last_activity.get(chat_id, now)
            if (now - last) < self._settings.session_idle_timeout:
                logger.debug("Chat %s became active during rotation wait, skipping", chat_id)
                return

            session_id = self._sessions.get(chat_id)
            if session_id is None:
                return

            logger.info("--- [ROTATE] Starting for chat %s (session: %s) ---", chat_id, session_id)

            # 1. Curate: run the dedicated curator agent against the session
            if self._curator_runner is not None:
                curation_content = types.Content(
                    role="user",
                    parts=[types.Part(text=_CURATION_PROMPT)],
                )
                try:
                    async for _event in self._curator_runner.run_async(
                        user_id=chat_id,
                        session_id=session_id,
                        new_message=curation_content,
                    ):
                        pass  # consume all events; side-effects happen via tools
                except Exception:
                    logger.exception("Error during curation for chat %s", chat_id)

            # 2. Flush: persist full session to daily log
            try:
                session = await self._runner.session_service.get_session(
                    app_name=self._settings.app_name,
                    user_id=chat_id,
                    session_id=session_id,
                )
                if session:
                    await self._memory_service.add_session_to_memory(session)
                    logger.info("Flushed session to daily log for chat %s", chat_id)
            except Exception:
                logger.exception("Error flushing session for chat %s", chat_id)

            # 3. Reset: delete old session and create a fresh one
            try:
                await self._runner.session_service.delete_session(
                    app_name=self._settings.app_name,
                    user_id=chat_id,
                    session_id=session_id,
                )
            except Exception:
                logger.exception("Error deleting old session for chat %s", chat_id)

            new_session = await self._runner.session_service.create_session(
                app_name=self._settings.app_name,
                user_id=chat_id,
            )
            self._sessions[chat_id] = new_session.id
            del self._last_activity[chat_id]
            logger.info("--- [ROTATE] Finished for chat %s (new session: %s) ---", chat_id, new_session.id)

    async def shutdown(self) -> None:
        """Curate and flush all active sessions before the process exits."""
        if not self._sessions:
            logger.info("No active sessions to curate on shutdown")
            return

        logger.info("--- [SHUTDOWN] Curating %d active session(s) ---", len(self._sessions))
        for chat_id in list(self._sessions):
            session_id = self._sessions.get(chat_id)
            if session_id is None:
                continue

            # Run the curator against each active session
            if self._curator_runner is not None:
                curation_content = types.Content(
                    role="user",
                    parts=[types.Part(text=_CURATION_PROMPT)],
                )
                try:
                    async for _event in self._curator_runner.run_async(
                        user_id=chat_id,
                        session_id=session_id,
                        new_message=curation_content,
                    ):
                        pass
                    logger.info("[SHUTDOWN] Curated session for chat %s", chat_id)
                except Exception:
                    logger.exception("[SHUTDOWN] Error curating chat %s", chat_id)

            # Flush session to daily log
            try:
                session = await self._runner.session_service.get_session(
                    app_name=self._settings.app_name,
                    user_id=chat_id,
                    session_id=session_id,
                )
                if session:
                    await self._memory_service.add_session_to_memory(session)
                    logger.info("[SHUTDOWN] Flushed session to daily log for chat %s", chat_id)
            except Exception:
                logger.exception("[SHUTDOWN] Error flushing session for chat %s", chat_id)

        logger.info("--- [SHUTDOWN] Memory curation complete ---")
