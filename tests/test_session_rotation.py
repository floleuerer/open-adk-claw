from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import pytest

from adk_claw.config import Settings
from adk_claw.dispatcher import Dispatcher, _CURATION_PROMPT
from adk_claw.queue import QueuedMessage


@dataclass
class FakeSession:
    id: str
    events: list = field(default_factory=list)


class FakeSessionService:
    """Minimal session service that tracks create/delete calls."""

    def __init__(self) -> None:
        self._counter = 0
        self.created: list[dict] = []
        self.deleted: list[dict] = []
        self._sessions: dict[str, FakeSession] = {}

    async def create_session(self, *, app_name: str, user_id: str) -> FakeSession:
        self._counter += 1
        sid = f"session-{self._counter}"
        session = FakeSession(id=sid)
        self._sessions[sid] = session
        self.created.append({"app_name": app_name, "user_id": user_id, "session_id": sid})
        return session

    async def get_session(self, *, app_name: str, user_id: str, session_id: str) -> FakeSession | None:
        return self._sessions.get(session_id)

    async def delete_session(self, *, app_name: str, user_id: str, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self.deleted.append({"app_name": app_name, "user_id": user_id, "session_id": session_id})


def _make_settings(**overrides) -> Settings:
    defaults = {
        "telegram_bot_token": "fake",
        "google_api_key": "fake",
        "session_idle_timeout": 0.3,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _make_dispatcher(
    session_service: FakeSessionService,
    memory_service: AsyncMock,
    run_async_side_effect=None,
    curator_run_async_side_effect=None,
) -> Dispatcher:
    runner = AsyncMock()
    runner.session_service = session_service

    async def _empty_run(**kwargs):
        return
        yield  # make it an async generator

    if run_async_side_effect is None:
        runner.run_async = _empty_run
    else:
        runner.run_async = run_async_side_effect

    curator_runner = AsyncMock()
    curator_runner.session_service = session_service
    if curator_run_async_side_effect is None:
        curator_runner.run_async = _empty_run
    else:
        curator_runner.run_async = curator_run_async_side_effect

    settings = _make_settings()
    send_reply = AsyncMock()
    return Dispatcher(runner, settings, memory_service, send_reply, curator_runner)


@pytest.mark.asyncio
async def test_rotate_session_curates_flushes_resets():
    """After idle timeout, rotation should: run curation, flush, delete+create."""
    session_service = FakeSessionService()
    memory_service = AsyncMock()

    curation_prompts: list[str] = []

    async def track_run_async(*, user_id, session_id, new_message):
        text = new_message.parts[0].text if new_message.parts else ""
        curation_prompts.append(text)
        return
        yield

    dispatcher = _make_dispatcher(session_service, memory_service, curator_run_async_side_effect=track_run_async)

    # Simulate a message to create a session
    msg = QueuedMessage(chat_id="chat1", text="hello", user_name="alice")
    await dispatcher.enqueue_chat("chat1", [msg])

    # Process the chat message
    item = await dispatcher._chat_queue.get()
    await dispatcher._process(item)
    dispatcher._chat_queue.task_done()

    assert "chat1" in dispatcher._sessions
    original_session_id = dispatcher._sessions["chat1"]
    assert session_service.created[-1]["session_id"] == original_session_id

    # Simulate time passing beyond the idle timeout
    dispatcher._last_activity["chat1"] = time.monotonic() - 1.0

    # Trigger rotation
    await dispatcher._rotate_session("chat1")

    # 1. Curation prompt was sent
    assert any(_CURATION_PROMPT in p for p in curation_prompts)

    # 2. Session was flushed to daily log
    memory_service.add_session_to_memory.assert_called_once()

    # 3. Old session deleted, new one created
    assert any(d["session_id"] == original_session_id for d in session_service.deleted)
    new_session_id = dispatcher._sessions["chat1"]
    assert new_session_id != original_session_id

    # Activity timestamp cleared
    assert "chat1" not in dispatcher._last_activity


@pytest.mark.asyncio
async def test_rotation_skipped_if_activity_resumes():
    """If user becomes active while waiting for lock, rotation is skipped."""
    session_service = FakeSessionService()
    memory_service = AsyncMock()
    dispatcher = _make_dispatcher(session_service, memory_service)

    # Create a session manually
    session = await session_service.create_session(app_name="adk-claw", user_id="chat1")
    dispatcher._sessions["chat1"] = session.id

    # Activity is recent — rotation should be skipped
    dispatcher._last_activity["chat1"] = time.monotonic()

    await dispatcher._rotate_session("chat1")

    # Nothing should have been deleted or flushed
    assert len(session_service.deleted) == 0
    memory_service.add_session_to_memory.assert_not_called()


@pytest.mark.asyncio
async def test_reaper_finds_idle_sessions():
    """The reaper coroutine identifies idle sessions and rotates them."""
    session_service = FakeSessionService()
    memory_service = AsyncMock()
    dispatcher = _make_dispatcher(session_service, memory_service)

    # Create a session and mark it as old
    session = await session_service.create_session(app_name="adk-claw", user_id="chat1")
    dispatcher._sessions["chat1"] = session.id
    dispatcher._last_activity["chat1"] = time.monotonic() - 1.0

    # Patch _REAPER_INTERVAL to run quickly and cancel after one cycle
    with patch("adk_claw.dispatcher._REAPER_INTERVAL", 0.05):
        reaper_task = asyncio.create_task(dispatcher._session_reaper())
        await asyncio.sleep(0.15)
        reaper_task.cancel()
        try:
            await reaper_task
        except asyncio.CancelledError:
            pass

    # Session should have been rotated
    assert len(session_service.deleted) == 1
    assert dispatcher._sessions["chat1"] != session.id


@pytest.mark.asyncio
async def test_message_during_rotation_waits():
    """Messages arriving during rotation wait for it to finish, then run on the new session."""
    session_service = FakeSessionService()
    memory_service = AsyncMock()

    call_log: list[str] = []

    async def tracking_run_async(*, user_id, session_id, new_message):
        text = new_message.parts[0].text if new_message.parts else ""
        call_log.append(f"{session_id}:{text[:20]}")
        return
        yield

    dispatcher = _make_dispatcher(session_service, memory_service, tracking_run_async)

    # Create initial session
    session = await session_service.create_session(app_name="adk-claw", user_id="chat1")
    dispatcher._sessions["chat1"] = session.id
    dispatcher._last_activity["chat1"] = time.monotonic() - 1.0
    original_id = session.id

    # Start rotation (holds the lock)
    rotate_task = asyncio.create_task(dispatcher._rotate_session("chat1"))

    # Give rotation a moment to acquire lock
    await asyncio.sleep(0.01)

    # Enqueue a message — it will wait for the lock
    msg = QueuedMessage(chat_id="chat1", text="new message", user_name="bob")
    process_task = asyncio.create_task(
        dispatcher._process(
            type("WorkItem", (), {"chat_id": "chat1", "messages": [msg], "lane": "chat"})()
        )
    )

    await rotate_task
    await process_task

    # The message should have run on the NEW session (not the old one)
    new_id = dispatcher._sessions["chat1"]
    assert new_id != original_id
    # Last call should be on the new session
    assert any(new_id in entry for entry in call_log)
