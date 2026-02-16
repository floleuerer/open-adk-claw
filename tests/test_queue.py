import asyncio

import pytest

from adk_claw.queue import MessageQueue, QueuedMessage


@pytest.mark.asyncio
async def test_single_message_fires():
    received = []

    async def on_batch(chat_id: str, messages: list[QueuedMessage]):
        received.append((chat_id, [m.text for m in messages]))

    queue = MessageQueue(debounce_seconds=0.1, on_batch=on_batch)
    await queue.push("chat1", "hello", "Alice")

    await asyncio.sleep(0.3)
    assert len(received) == 1
    assert received[0] == ("chat1", ["hello"])


@pytest.mark.asyncio
async def test_debounce_coalesces():
    received = []

    async def on_batch(chat_id: str, messages: list[QueuedMessage]):
        received.append((chat_id, [m.text for m in messages]))

    queue = MessageQueue(debounce_seconds=0.2, on_batch=on_batch)
    await queue.push("chat1", "msg1", "Alice")
    await asyncio.sleep(0.05)
    await queue.push("chat1", "msg2", "Alice")
    await asyncio.sleep(0.05)
    await queue.push("chat1", "msg3", "Alice")

    await asyncio.sleep(0.4)
    assert len(received) == 1
    assert received[0] == ("chat1", ["msg1", "msg2", "msg3"])


@pytest.mark.asyncio
async def test_separate_chats():
    received = []

    async def on_batch(chat_id: str, messages: list[QueuedMessage]):
        received.append((chat_id, [m.text for m in messages]))

    queue = MessageQueue(debounce_seconds=0.1, on_batch=on_batch)
    await queue.push("chat1", "hello", "Alice")
    await queue.push("chat2", "world", "Bob")

    await asyncio.sleep(0.3)
    assert len(received) == 2
    chat_ids = {r[0] for r in received}
    assert chat_ids == {"chat1", "chat2"}


@pytest.mark.asyncio
async def test_debounce_resets_timer():
    received = []

    async def on_batch(chat_id: str, messages: list[QueuedMessage]):
        received.append((chat_id, [m.text for m in messages]))

    queue = MessageQueue(debounce_seconds=0.2, on_batch=on_batch)
    await queue.push("chat1", "msg1", "Alice")
    await asyncio.sleep(0.15)
    # This should reset the timer
    await queue.push("chat1", "msg2", "Alice")
    await asyncio.sleep(0.15)

    # Timer hasn't fired yet (0.15s since last push, need 0.2s)
    assert len(received) == 0

    await asyncio.sleep(0.15)
    # Now it should have fired
    assert len(received) == 1
    assert received[0] == ("chat1", ["msg1", "msg2"])
