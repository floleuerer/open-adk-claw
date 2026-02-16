from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


@dataclass
class QueuedMessage:
    chat_id: str
    text: str
    user_name: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


OnBatchCallback = Callable[[str, list[QueuedMessage]], Awaitable[None]]


class MessageQueue:
    def __init__(self, debounce_seconds: float, on_batch: OnBatchCallback) -> None:
        self._debounce = debounce_seconds
        self._on_batch = on_batch
        self._buffers: dict[str, list[QueuedMessage]] = {}
        self._timers: dict[str, asyncio.Task] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, chat_id: str) -> asyncio.Lock:
        if chat_id not in self._locks:
            self._locks[chat_id] = asyncio.Lock()
        return self._locks[chat_id]

    async def push(self, chat_id: str, text: str, user_name: str) -> None:
        lock = self._get_lock(chat_id)
        async with lock:
            if chat_id not in self._buffers:
                self._buffers[chat_id] = []

            self._buffers[chat_id].append(QueuedMessage(
                chat_id=chat_id,
                text=text,
                user_name=user_name,
            ))

            # Cancel existing timer and start a new one
            if chat_id in self._timers:
                self._timers[chat_id].cancel()

            self._timers[chat_id] = asyncio.create_task(
                self._debounce_fire(chat_id)
            )

    async def _debounce_fire(self, chat_id: str) -> None:
        await asyncio.sleep(self._debounce)

        lock = self._get_lock(chat_id)
        async with lock:
            messages = self._buffers.pop(chat_id, [])
            self._timers.pop(chat_id, None)

        if messages:
            logger.info("Firing batch of %d messages for chat %s", len(messages), chat_id)
            try:
                await self._on_batch(chat_id, messages)
            except Exception:
                logger.exception("Error processing batch for chat %s", chat_id)
